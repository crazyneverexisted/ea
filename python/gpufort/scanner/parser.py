# SPDX-License-Identifier: MIT
# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
import os, sys, traceback
import subprocess
import copy
import argparse
import itertools
import hashlib
from collections import Iterable # < py38
import importlib

import re
import pyparsing

from gpufort import util
from gpufort import linemapper
from gpufort import translator
from gpufort import indexer

from . import tree
from . import opts

# Pyparsing actions that create scanner tree (ST)
@util.logging.log_entry_and_exit(opts.log_prefix)
def _parse_file(linemaps, index, **kwargs):
    """Generates a tree representation of the Fortran constructs
    in a Fortran file that is called *scanner tree*.
    :param list linemaps: List of linemaps created by GPUFORT's linemapper
                          component.
    :param list index: Index records created by GPUFORT's indexer
                       component.
    """
    modern_fortran,_ = util.kwargs.get_value("modern_fortran",opts.modern_fortran,**kwargs)
    cuda_fortran  ,_ = util.kwargs.get_value("cuda_fortran","cuf" in opts.source_dialects,**kwargs)
    openacc       ,_ = util.kwargs.get_value("openacc","acc" in opts.source_dialects,**kwargs)
    translation_enabled_by_default,_ = util.kwargs.get_value("translation_enabled_by_default",opts.translation_enabled_by_default,**kwargs)
    
    translation_enabled = translation_enabled_by_default
    current_node = tree.STRoot()
    do_loop_labels = []
    keep_recording = False
    fortran_file_path = linemaps[0]["file"]
    current_file = str(fortran_file_path)
    current_linemap = None
    current_tokens = None
    derived_type_parent = None
    acc_kernels_directive = None
    statement_functions = []

    def set_keep_recording_(state):
        nonlocal keep_recording
        nonlocal current_node
        nonlocal current_linemap
        if state:
            util.logging.log_debug(opts.log_prefix,"parse_file","[current-node={}:{}] start recording lines in line {}".format(
                current_node.kind,current_node.name,current_linemap["lineno"]))
        else:
            util.logging.log_debug(opts.log_prefix,"parse_file","[current-node={}:{}] stop recording lines in line {}".format(
                current_node.kind,current_node.name,current_linemap["lineno"]))
        keep_recording = state
    
    def log_detection_(kind):
        nonlocal current_node
        nonlocal current_linemap
        util.logging.log_debug2(opts.log_prefix,"parse_file","[current-node={}:{}] found {} in line {}: '{}'".format(\
                current_node.kind,current_node.name,kind,current_linemap["lineno"],current_linemap["lines"][0].rstrip("\n")))

    def append_if_not_recording_(new):
        nonlocal current_node
        nonlocal keep_recording
        if not keep_recording:
            new.parent = current_node
            current_node.append(new)

    def descend_(new):
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        parent_node_id = current_node.kind
        parent_node_name = current_node.name

        new.parent = current_node
        current_node.append(new)
        current_node = new

        current_node_id = current_node.kind
        if current_node.name != None:
            current_node_id += " '" + current_node.name + "'"
        if parent_node_name != None:
            parent_node_id += ":" + parent_node_name

        util.logging.log_debug(opts.log_prefix,"parse_file","[current-node={0}] enter {1} in line {2}: '{3}'".format(\
          parent_node_id,current_node_id,current_linemap["lineno"],current_linemap["lines"][0].rstrip("\n")))

    def ascend_():
        nonlocal current_node
        nonlocal current_file
        nonlocal current_linemap
        nonlocal current_statement_no
        assert not current_node.parent is None, "In file {}: parent of {} is none".format(
            current_file, type(current_node))
        current_node_id = current_node.kind
        if current_node.name != None:
            current_node_id += " '" + current_node.name + "'"
        parent_node_id = current_node.parent.kind
        if current_node.parent.name != None:
            parent_node_id += ":" + current_node.parent.name

        util.logging.log_debug(opts.log_prefix,"parse_file","[current-node={0}] leave {1} in line {2}: '{3}'".format(\
          parent_node_id,current_node_id,current_linemap["lineno"],current_linemap["lines"][0].rstrip("\n")))
        current_node = current_node.parent

    # parse actions
    def ModuleStart():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal current_tokens
        log_detection_("module")
        new = tree.STModule(current_tokens[1], current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        descend_(new)

    def ProgramStart():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal current_tokens
        log_detection_("program")
        # TODO workaround, this will only allow local statement functions
        statement_functions.clear()
        new = tree.STProgram(current_tokens[1], current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        descend_(new)
    
    def TypeStart():
        nonlocal derived_type_parent
        nonlocal current_statement_stripped_no_comments
        log_detection_("type")
        name, _, __ = util.parsing.parse_derived_type_statement(current_statement_stripped_no_comments)
        derived_type_parent = name
    
    def TypeEnd():
        nonlocal derived_type_parent
        log_detection_("end program")
        derived_type_parent = None
        new = tree.STPlaceHolder(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def FunctionStart(tokens):
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal keep_recording
        nonlocal index
        log_detection_("function")
        # TODO workaround, this will only allow local statement functions
        statement_functions.clear()
        new = tree.STProcedure(tokens[1],current_node.tag(),"function",\
            current_linemap,current_statement_no,index)
        new.ignore_in_s2s_translation = not translation_enabled
        set_keep_recording_(new.keep_recording())
        descend_(new)

    def SubroutineStart(tokens):
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal keep_recording
        nonlocal index
        log_detection_("subroutine")
        # TODO workaround, this will only allow local statement functions
        statement_functions.clear()
        new = tree.STProcedure(tokens[1],current_node.tag(),"subroutine",\
            current_linemap,current_statement_no,index)
        new.ignore_in_s2s_translation = not translation_enabled
        set_keep_recording_(new.keep_recording())
        descend_(new)

    def End():
        nonlocal current_node
        nonlocal current_linemap
        nonlocal keep_recording
        nonlocal index
        log_detection_("end of module/program/function/subroutine")
        assert type(current_node) in [
            tree.STModule, tree.STProgram, tree.STProcedure
        ], "In file {}: line {}: type is {}".format(current_file,
                                                    current_statement_no,
                                                    type(current_node))
        if type(
                current_node
        ) is tree.STProcedure and current_node.must_be_available_on_device():
            current_node.add_linemap(current_linemap)
            current_node._last_statement_index = current_statement_no
            current_node.complete_init(index)
            set_keep_recording_(False)
        if not keep_recording:
            new = tree.STEnd(current_linemap, current_statement_no)
            append_if_not_recording_(new)
        ascend_()

    def Return():
        nonlocal current_node
        nonlocal current_linemap
        nonlocal keep_recording
        log_detection_("return statement")
        if not keep_recording and isinstance(
                current_node, (tree.STProcedure, tree.STProgram)):
            new = tree.STReturn(current_linemap, current_statement_no)
            append_if_not_recording_(new)

    def in_kernels_acc_region_and_not_recording():
        nonlocal keep_recording
        nonlocal acc_kernels_directive
        return not keep_recording and acc_kernels_directive != None

    def DoLoopStart():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_tokens
        nonlocal current_linemap
        nonlocal do_loop_labels
        nonlocal keep_recording
        nonlocal acc_kernels_directive
        log_detection_("do loop")
        if not util.parsing.is_do_while(current_tokens):
            parse_result = util.parsing.parse_do_statement(" ".join(current_tokens))
            label = parse_result[0]
        else:
            label = None
        if (in_kernels_acc_region_and_not_recording() and
           not util.parsing.is_do_while(current_tokens)):
            new = tree.acc.STAccComputeConstruct(current_linemap, current_statement_no, acc_kernels_directive)
            new.ignore_in_s2s_translation = not translation_enabled
            new._do_loop_ctr_memorised = len(do_loop_labels)
            descend_(new)
            set_keep_recording_(True)
        do_loop_labels.append(label)

    def DoLoopEnd():
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal do_loop_labels
        nonlocal keep_recording
        nonlocal index
        log_detection_("end of do loop")
        if isinstance(current_node, tree.STComputeConstruct):
            if keep_recording and current_node._do_loop_ctr_memorised == len(do_loop_labels):
                current_node.add_linemap(current_linemap)
                current_node._last_statement_index = current_statement_no
                current_node.complete_init(index)
                ascend_()
                set_keep_recording_(False)

    def Declaration():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal derived_type_parent
        log_detection_("declaration")
        new = tree.STDeclaration(current_linemap, current_statement_no)
        new.derived_type_parent = derived_type_parent
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def Attributes(tokens):
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("attributes statement")
        new = tree.STCufAttributes(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        current_node.append(new)

    def UseStatement(tokens):
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("use statement")
        new = tree.STUseStatement(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        new.name = translator.tree.make_f_str(
            tokens[1]) # just get the name, ignore specific includes
        append_if_not_recording_(new)

    def PlaceHolder():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("placeholder")
        new = tree.STPlaceHolder(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def Contains():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("contains")
        new = tree.STContains(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def NonZeroCheck(tokens):
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("non-zero check")
        new = tree.STNonZeroCheck(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def Allocated(tokens):
        nonlocal current_node
        nonlocal translation_enabled
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("allocated statement")
        new = tree.STAllocated(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def Allocate():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("allocate statement")
        new = tree.STAllocate(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def Deallocate():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("deallocate statement")
        # TODO filter variable, replace with hipFree
        new = tree.STDeallocate(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def CufMemcpy():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        log_detection_("memcpy")
        new = tree.STCufMemcpy(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def CufLibCall(tokens):
        #TODO scan for cudaCufMemcpy calls
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal keep_recording
        log_detection_("CUDA API call")
        cudaApi, args = tokens
        if not type(current_node) in [tree.cuf.STCufLibCall, tree.cuf.STCufKernelCall]:
            new = tree.cuf.STCufLibCall(current_linemap, current_statement_no)
            new.ignore_in_s2s_translation = not translation_enabled
            new.cudaApi = cudaApi
            #print("finishes_on_first_line={}".format(finishes_on_first_line))
            #assert type(new.parent) in [
            #    tree.STModule, tree.STProcedure, tree.STProgram
            #], type(new.parent)
            append_if_not_recording_(new)

    def CufKernelCall(tokens):
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal keep_recording
        log_detection_("CUDA kernel call")
        kernel_name, kernel_launch_args, args = tokens
        assert type(current_node) in [
            tree.STModule, tree.STProcedure, tree.STProgram
        ], "type is: " + str(type(current_node))
        new = tree.cuf.STCufKernelCall(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        append_if_not_recording_(new)

    def AccDirective():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal keep_recording
        nonlocal do_loop_labels
        nonlocal acc_kernels_directive
        log_detection_("OpenACC directive")
        new = tree.acc.STAccDirective(current_linemap, current_statement_no)
        new.ignore_in_s2s_translation = not translation_enabled
        # if end directive ascend
        if (new.is_directive(["acc","end","kernels"]) 
           and acc_kernels_directive != None):
            acc_kernels_directive = None
            append_if_not_recording_(new)
            util.logging.log_debug(opts.log_prefix,"_parse_file","leave acc kernels region")
        # descend in constructs or new node
        elif (new.is_directive(["acc","serial"]) # TODO this assumes that there will be always an acc loop afterwards
             or  new.is_directive(["acc","parallel"]) # TODO this assumes that there will be always an acc loop afterwards
             or new.is_directive(["acc","parallel","loop"])
             or new.is_directive(["acc","kernels","loop"])
             or (acc_kernels_directive != None
                and new.is_directive(["acc","loop"]))):
            new = tree.acc.STAccComputeConstruct(current_linemap, current_statement_no, acc_kernels_directive)
            new.kind = "acc-compute-construct"
            new.ignore_in_s2s_translation = not translation_enabled
            new._do_loop_ctr_memorised = len(do_loop_labels)
            descend_(new) # descend also appends
            set_keep_recording_(True)
        elif new.is_directive(["acc","kernels"]):
            acc_kernels_directive = new.first_statement()
            append_if_not_recording_(new)
            util.logging.log_debug(opts.log_prefix,"_parse_file","enter acc kernels region")
        else:
            # append new directive
            append_if_not_recording_(new)

    def CufLoopNest():
        nonlocal translation_enabled
        nonlocal current_node
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal do_loop_labels
        nonlocal keep_recording
        log_detection_("CUDA Fortran loop kernel directive")
        new = tree.cuf.STCufLoopNest(current_linemap, current_statement_no)
        new.kind = "cuf-kernel-do"
        new.ignore_in_s2s_translation = not translation_enabled
        new._do_loop_ctr_memorised = len(do_loop_labels)
        descend_(new)
        set_keep_recording_(True)

    def Assignment(lhs_ivar,lhs_expr):
        nonlocal current_node
        nonlocal translation_enabled
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal current_statement
        nonlocal current_tokens
        nonlocal acc_kernels_directive
        nonlocal index
        log_detection_("assignment")
        if in_kernels_acc_region_and_not_recording() or lhs_ivar["rank"] == 0:
            parse_result = translator.tree.grammar.assignment_begin.parseString(
                current_statement["body"])
            lvalue = translator.tree.find_first(parse_result, translator.tree.TTLValue)
            # TODO
            
            if (in_kernels_acc_region_and_not_recording()
               and lhs_ivar["rank"] > 0 
               and (lvalue.has_range_args() 
                   or not lvalue.has_args())):
                new = tree.acc.STAccComputeConstruct(
                        current_linemap,
                        current_statement_no,
                        acc_kernels_directive)
                new.ignore_in_s2s_translation = not translation_enabled
                append_if_not_recording_(new)
                new.complete_init(index)
            elif (not in_kernels_acc_region_and_not_recording()
                 and lhs_ivar["rank"] == 0 
                 and lvalue.has_args() 
                 and lhs_ivar["f_type"] in ["integer","real","logical"]):
                    if util.parsing.is_derived_type_member_access(util.parsing.tokenize(lhs_expr)):
                        raise util.error.SyntaxError("result of statement function must not be derived type member")
                    name, args, rhs_expr =\
                        util.parsing.parse_statement_function(current_statement["body"])
                    name = name.lower()
                    existing_record = next((entry for entry in statement_functions
                                           if entry[0] == name),None)
                    if existing_record == None:
                        statement_functions.append((name,args,rhs_expr))
                    else:
                        # TODO currently does not make sense as the statement variables are only 
                        # TODOc applied on the LHS of a statement; should only be applied to RHS
                        # of assignments
                        raise util.error.SyntaxError("redefinition of statement funtion")


    def GpufortControl():
        nonlocal current_statement
        nonlocal translation_enabled
        log_detection_("gpufortran control statement")
        if "on" in current_statement["body"]:
            translation_enabled = True
        elif "off" in current_statement["body"]:
            translation_enabled = False

    # TODO completely remove / comment out !$acc end kernels
    tree.grammar.function_start.setParseAction(FunctionStart)
    tree.grammar.subroutine_start.setParseAction(SubroutineStart)

    tree.grammar.use.setParseAction(UseStatement)

    tree.grammar.attributes.setParseAction(Attributes)
    tree.grammar.ALLOCATED.setParseAction(Allocated)
    tree.grammar.non_zero_check.setParseAction(NonZeroCheck)

    # CUDA Fortran
    tree.grammar.cuda_lib_call.setParseAction(CufLibCall)
    tree.grammar.cuf_kernel_call.setParseAction(CufKernelCall)

    # OpenACC
    tree.grammar.ACC_START.setParseAction(AccDirective)

    # GPUFORT control
    tree.grammar.gpufort_control.setParseAction(GpufortControl)

    current_file = str(fortran_file_path)
    current_node.children.clear()

    def expand_statement_functions_(statement):
        """Expands Fortran statement functions in the given statement."""
        if len(statement_functions):
            stmt = statement["body"]
            statement["body"] = util.macros.expand_macros(stmt,statement_functions,
                    ignore_case=True,wrap_in_brackets=True)

    def scan_string_(expression_name, expression):
        """
        These expressions might be hidden behind a single-line if.
        """
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal current_statement

        matched = len(expression.searchString(current_statement["body"], 1))
        if matched:
            util.logging.log_debug3(
                opts.log_prefix, "parse_file.scanString",
                "found expression '{}' in line {}: '{}'".format(
                    expression_name, current_linemap["lineno"],
                    current_linemap["lines"][0].rstrip()))
        else:
            util.logging.log_debug4(
                opts.log_prefix, "parse_file.scanString",
                "did not find expression '{}' in line {}: '{}'".format(
                    expression_name, current_linemap["lineno"],
                    current_linemap["lines"][0].rstrip()))
        return matched

    def try_to_parse_string_(expression_name, expression, parseAll=False):
        """
        These expressions might never be hidden behind a single-line if or might
        never be an argument of another calls.
        No need to check if comments are in the line as the first
        words of the line must match the expression.
        """
        nonlocal current_linemap
        nonlocal current_statement_no
        nonlocal current_statement_stripped_no_comments

        try:
            expression.parseString(current_statement_stripped_no_comments,
                                   parseAll)
            util.logging.log_debug3(
                opts.log_prefix, "parse_file.try_to_parse_string_",
                "found expression '{}' in line {}: '{}'".format(
                    expression_name, current_linemap["lineno"],
                    current_linemap["lines"][0].rstrip()))
            return True
        except pyparsing.ParseBaseException as e:
            util.logging.log_debug4(
                opts.log_prefix, "parse_file.try_to_parse_string_",
                "did not find expression '{}' in line '{}'".format(
                    expression_name, current_linemap["lines"][0]))
            util.logging.log_debug5(opts.log_prefix,
                                    "parse_file.try_to_parse_string_", str(e))
            return False

    def is_end_statement_(tokens, kind):
        result = tokens[0] == "end" + kind
        if not result and len(tokens):
            result = tokens[0] == "end" and tokens[1] == kind
        return result

    # parser loop
    for current_linemap in linemaps:
        condition1 = current_linemap["is_active"]
        condition2 = len(current_linemap["included_linemaps"]
                        ) or not current_linemap["is_preprocessor_directive"]
        if condition1 and condition2:
            for current_statement_no, current_statement in enumerate(
                    current_linemap["statements"]):
                try:
                    expand_statement_functions_(current_statement)
                    original_statement_lower = current_statement["body"].lower()
                    util.logging.log_debug4(opts.log_prefix,"parse_file","parsing statement '{}' associated with lines [{},{}]".format(original_statement_lower.rstrip(),\
                        current_linemap["lineno"],current_linemap["lineno"]+len(current_linemap["lines"])-1))
                    current_tokens = util.parsing.tokenize(original_statement_lower, padded_size=6)
                    current_statement_stripped = " ".join([tk for tk in current_tokens if len(tk)])
                    current_statement_stripped_no_comments = current_statement_stripped.split(
                        "!")[0]
                    if (not keep_recording 
                       and util.parsing.is_fortran_directive(original_statement_lower,modern_fortran)):
                        if openacc and current_tokens[1] == "acc":
                            AccDirective()
                        elif cuda_fortran and current_tokens[1:4] == ["cuf","kernel","do"]:
                            CufLoopNest()
                        elif current_tokens[1] == "gpufort":
                            GpufortControl()
                    elif not util.parsing.is_fortran_comment(original_statement_lower,modern_fortran):
                        # constructs
                        if util.parsing.is_do_while(current_tokens):
                            pass # do nothing
                        if util.parsing.is_do(current_tokens):
                            DoLoopStart()
                        elif current_tokens[0:2] == ["end","do"]:
                            do_loop_labels.pop(-1)
                            DoLoopEnd()
                        elif (len(do_loop_labels) 
                             and current_tokens[0:2] == [do_loop_labels[-1],"continue"]):
                            # continue can be shared by multiple loops, e.g.:
                            # do 10 i = ...
                            # do 10 j = ...
                            # 10 continue
                            while len(do_loop_labels) and do_loop_labels[-1] == current_tokens[0]:
                                do_loop_labels.pop(-1)
                            DoLoopEnd()
                        elif (current_tokens[0] == "end"
                             and current_tokens[1] != "type"
                             and  current_tokens[1] not in indexer.ignored_constructs): 
                            End()
                        # single-statements
                        elif not keep_recording:
                            # TODO parse Fortran statements and apply these 
                            # constructs as cuda_fortran-specific postprocessing
                            if cuda_fortran:
                                if current_tokens[0] == "attributes":
                                    try_to_parse_string_("attributes",
                                                        tree.grammar.attributes)
                                elif "<<<" in current_tokens:
                                    try_to_parse_string_(
                                        "cuf_kernel_call",
                                        tree.grammar.cuf_kernel_call)
                                if "cu" in current_statement_stripped_no_comments:
                                    scan_string_("cuda_lib_call",
                                                tree.grammar.cuda_lib_call)
                                if "allocated" in current_tokens:
                                    scan_string_("allocated", tree.grammar.ALLOCATED)
                                if ("/=" in current_statement_stripped_no_comments
                                     or ".ne." in current_statement_stripped_no_comments.lower()):
                                    scan_string_("non_zero_check",
                                                tree.grammar.non_zero_check)
                            if (not util.parsing.is_do(current_tokens) # TODO Can user name the variables after keywords?
                               and not util.parsing.is_where(current_tokens) 
                               and util.parsing.is_assignment(current_tokens)):
                                lhs_expr, rhs_expr = util.parsing.parse_assignment(current_statement["body"])
                                lhs_ivar = indexer.scope.search_index_for_var(index,current_node.tag(),lhs_expr)
                                cuf_implicit_memcpy = "device" in lhs_ivar["qualifiers"]
                                if cuda_fortran:
                                    try:
                                        rhs_ivar = indexer.scope.search_index_for_var(index,current_node.tag(),
                                                rhs_expr)
                                        cuf_implicit_memcpy = cuf_implicit_memcpy or "device" in rhs_ivar["qualifiers"]
                                    except util.error.LookupError as e:
                                        if cuf_implicit_memcpy: 
                                            raise util.error.LimitationError("implicit to-device memcpy does not support arithmetic expression as right-hand side value") from e
                                if cuf_implicit_memcpy:
                                    CufMemcpy()
                                elif not cuf_implicit_memcpy:
                                    Assignment(lhs_ivar,lhs_expr)
                                    # TODO
                            elif current_tokens[0] == "deallocate":
                                Deallocate()
                            elif current_tokens[0] == "allocate":
                                Allocate()
                            elif current_tokens[0] == "end":
                                if current_tokens[1] == "type":
                                    TypeEnd()
                            elif current_tokens[0] == "use":
                                try_to_parse_string_("use", tree.grammar.use)
                            elif current_tokens[0] == "implicit":
                                PlaceHolder()
                            elif current_tokens[0] == "contains":
                                Contains()
                            elif current_tokens[0] == "module" and current_tokens[1] != "procedure":
                                ModuleStart()
                            elif current_tokens[0] == "program":
                                ProgramStart()
                            elif "function" in current_tokens:
                                try_to_parse_string_("function",
                                                    tree.grammar.function_start)
                            elif "subroutine" in current_tokens:
                                try_to_parse_string_("subroutine",
                                                    tree.grammar.subroutine_start)
                            elif current_tokens[0] == "return":
                                Return()
                            #
                            # TODO build proper parser of function / subroutine
                            # plus corresponding detection criterion
                            elif (not "function" in current_tokens 
                                 and current_tokens[0] in [
                                    "character", "integer", "logical", "real",
                                    "complex", "double"
                                ]):
                                Declaration() 
                            elif (not "function" in current_tokens 
                                 and current_tokens[0] == "type" 
                                 and current_tokens[1] == "("):
                                Declaration() 
                            elif current_tokens[0] == "type": # must come after declarations
                                TypeStart()
                    if keep_recording:
                        current_node.add_linemap(current_linemap)
                        current_node._last_statement_index = current_statement_no
                except (util.error.SyntaxError, util.error.LimitationError, util.error.LookupError) as e:
                    msg = "{}:{}:{}".format(
                            current_linemap["file"],current_linemap["lineno"],e.args[0])
                    e.args = (msg,)
                    raise

    assert type(current_node) is tree.STRoot
    return current_node


def parse_file(**kwargs):
    r"""Create scanner tree from file content.
    :param \*\*kwargs: See below.
    :return: a triple of scanner tree root node, (updated) index, and linemaps

    :Keyword Arguments:
    
    * *file_path* (``str``):
        Path to the file that should be parsed.
    * *file_content* (``str``):
        Content of the file that should be parsed.
    * *file_linemaps* (``list``):
        Linemaps of the file that should be parsed;
        see GPUFORT's linemapper component.
    * *file_is_indexed* (``bool``):
        Index already contains entries for the main file.
    * *preproc_options* (``str``): Options to pass to the C preprocessor
        of the linemapper component.
    * *other_files_paths* (``list(str)``):
        Paths to other files that contain module files that
        contain definitions required for parsing the main file.
        NOTE: It is assumed that these files have not been indexed yet.
    * *other_files_contents* (``list(str)``):
        Content that contain module files that
        contain definitions required for parsing the main file.
        NOTE: It is assumed that these files have not been indexed yet.
    * *index* (``list``):
        Index records created via GPUFORT's indexer component.
    """
    # Determine if there is an index arg and
    # what has already been indexed
    index, have_index = util.kwargs.get_value("index", [], **kwargs)
    file_is_indexed, _ = util.kwargs.get_value("file_is_indexed", have_index,
                                               **kwargs)
    # handle main file
    file_content, have_file_content = util.kwargs.get_value(
        "file_content", None, **kwargs)
    linemaps, have_linemaps = util.kwargs.get_value("file_linemaps", None,
                                                    **kwargs)
    file_path, have_file_path = util.kwargs.get_value("file_path", "<unknown>",
                                                      **kwargs)
    if not have_file_content and not have_linemaps:
        if not have_file_path:
            raise ValueError(
                "Missing keyword argument: At least one of `file_path`, `file_content`, `linemaps` must be specified."
            )
        with open(file_path, "r") as infile:
            file_content = infile.read()
    if not have_linemaps:
        linemaps = linemapper.read_lines(
            file_content.splitlines(keepends=True), **kwargs)
    if not file_is_indexed:
        indexer.update_index_from_linemaps(linemaps, index)

    # handles dependencies
    other_files_contents, have_other_files_contents = util.kwargs.get_value(
        "other_files_contents", [], **kwargs)
    other_files_paths, have_other_files_paths = util.kwargs.get_value(
        "other_files_paths", [], **kwargs)
    if have_other_files_paths:
        for path in other_files_paths:
            with open(path, "r") as infile:
                other_files_contents.append(infile.read())
    for content in other_files_contents:
        indexer.update_index_from_snippet(index, content, **kwargs)
    if "index" in kwargs:
        kwargs.pop("index")
    return _parse_file(linemaps, index, **kwargs), index, linemaps


__all__ = ["parse_file"]
