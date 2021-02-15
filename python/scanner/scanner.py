#!/usr/bin/env python3
import os, sys, traceback
import subprocess
import copy
import argparse
import itertools
import hashlib
from collections import Iterable # < py38
import importlib
import logging

import yaml

import re

# local includes
import addtoplevelpath
import translator.translator as translator

# dirty hack that allows us to load independent versions of the grammar module
#from grammar import *
grammarDir = os.path.join(os.path.dirname(__file__),"../grammar")
print(grammarDir)
exec(open("{0}/grammar_options.py.in".format(grammarDir)).read())
exec(open("{0}/grammar_f03.py.in".format(grammarDir)).read())
exec(open("{0}/grammar_cuf.py.in".format(grammarDir)).read())
exec(open("{0}/grammar_acc.py.in".format(grammarDir)).read())
exec(open("{0}/grammar_epilog.py.in".format(grammarDir)).read())

scannerDir = os.path.dirname(__file__)
exec(open("{0}/scanner_options.py.in".format(scannerDir)).read())
exec(open("{0}/scanner_tree.py.in".format(scannerDir)).read())
exec(open("{0}/scanner_tree_acc.py.in".format(scannerDir)).read())
exec(open("{0}/scanner_groups.py.in".format(scannerDir)).read())
    
def handleIncludeStatements(fortranFilePath,lines):
    """
    Copy included files' content into current file.
    """
    def processLine(line):
        if "#include" in line.lower():
            relativeSnippetPath = line.split(' ')[-1].replace('\"','').replace('\'','').strip()
            snippetPath = os.path.dirname(fortranFilePath) + "/" + relativeSnippetPath
            try:
                result = ["! {stmt}\n".format(stmt=line)]
                result.append("! begin gpufort include\n")
                result += open(snippetPath,"r").readlines()
                result.append("! end gpufort include\n")
                print("processed include: "+line.strip())
                return result
            except Exception as e:
                raise e
                return [line]
        else:
            return [line]
     
    result = []
    for line in lines:
        result += processLine(line)
    return result

# Pyparsing Actions that create scanner tree (ST)
def parseFile(fortranFilePath):
    """
    Generate an object tree (OT). 
    """
    current=STRoot()
    doLoopCtr = 0     
    keepRecording = False
    currentFile = str(fortranFilePath)
    currentLineno = -1
    currentLines  = []
    directiveNo   = 0

    def descend(new):
        nonlocal current
        current.append(new)
        current=new
    def ascend():
        nonlocal current
        nonlocal currentFile
        assert not current._parent is None, "In file {}: parent of {} is none".format(currentFile,type(current))
        current = current._parent
   
    # parse actions
    def Module_visit(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STModule(tokens[0],current,currentLineno)
        descend(new)
    def Program_visit(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STProgram(tokens[0],current,currentLineno)
        descend(new)
    def Function_visit(tokens):
        nonlocal current
        nonlocal keepRecording
        new = STFunction(qualifier=tokens[0],name=tokens[1],dummyVars=tokens[2],\
                parent=current,lineno=currentLineno,lines=currentLines)
        if new.qualifier.lower() in ["global","device","host,device"]:
            keepRecording = True
        descend(new)
    def Subroutine_visit(tokens):
        nonlocal current
        nonlocal keepRecording
        new = STSubroutine(qualifier=tokens[0],name=tokens[1],dummyVars=tokens[2],\
                parent=current,lineno=currentLineno,lines=currentLines)
        if new._qualifier.lower() in ["global","device"]:
            keepRecording = True
        descend(new)
    def Structure_leave(tokens):
        nonlocal current
        nonlocal keepRecording
        assert type(current) in [STModule,STProgram,STSubroutine,STFunction], "In file {}: line {}: type is {}".format(currentFile, currentLineno, type(current))
        if type(current) in [STSubroutine,STFunction] and current._qualifier.lower() in ["global","device"]:
            current._lines += currentLines
            keepRecording = False
        ascend()
    def DoLoop_visit(tokens):
        nonlocal keepRecording
        nonlocal doLoopCtr
        if inParallelAccRegionAndNotRecording():
            new = STAccLoopKernel(parent=current,lineno=currentLineno,lines=currentLines)
            new._directiveLines = current._directiveLines
            new._lines = []
            new._doLoopCtrMemorised=doLoopCtr
            descend(new) 
            keepRecording = True
        doLoopCtr += 1
    def DoLoop_leave(tokens):
        nonlocal current
        nonlocal currentLines
        nonlocal doLoopCtr
        nonlocal keepRecording
        doLoopCtr -= 1
        if isinstance(current, STLoopKernel):
            if keepRecording and current._doLoopCtrMemorised == doLoopCtr:
                current._lines += currentLines
                ascend()
                keepRecording = False
    def CufLoopKernel(tokens):
        nonlocal doLoopCtr
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        nonlocal keepRecording
        new = STCufLoopKernel(parent=current,lineno=currentLineno,lines=currentLines)
        new._directiveLines = currentLines
        new._doLoopCtrMemorised=doLoopCtr
        descend(new) 
        keepRecording = True
    def Declaration(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STDeclaration(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def Attributes(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STAttributes(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def UseStatement(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STUseStatement(parent=current,lineno=currentLineno,lines=currentLines)
        new._name = translator.makeFStr(tokens[1]) # just get the name, ignore specific includes
        current.append(new)
    def PlaceHolder(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STPlaceHolder(current,currentLineno,currentLines)
        current.append(new)
    def NonZeroCheck(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new=STNonZeroCheck(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def Allocated(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new=STAllocated(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def Allocate(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new=STAllocate(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def Deallocate(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        # TODO filter variable, replace with hipFree
        new = STDeallocate(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def Memcpy(tokens):
        nonlocal current
        nonlocal currentLineno
        nonlocal currentLines
        new = STMemcpy(parent=current,lineno=currentLineno,lines=currentLines)
        current.append(new)
    def CudaLibCall(tokens):
        #TODO scan for cudaMemcpy calls
        nonlocal current
        nonlocal currentLines
        nonlocal keepRecording
        cudaApi, args, finishesOnFirstLine = tokens 
        if not type(current) in [STCudaLibCall,STCudaKernelCall]:
            new = STCudaLibCall(parent=current,lineno=currentLineno,lines=currentLines) 
            new.cudaApi  = cudaApi
            #print("finishesOnFirstLine={}".format(finishesOnFirstLine))
            assert type(new._parent) in [STModule,STFunction,STSubroutine,STProgram], type(new._parent)
            new._lines = currentLines
            current.append(new)
    def CudaKernelCall(tokens):
        nonlocal current
        nonlocal currentLines
        nonlocal keepRecording
        kernelName, kernelLaunchArgs, args, finishesOnFirstLine = tokens 
        assert type(current) in [STModule,STFunction,STSubroutine,STProgram], "type is: "+str(type(current))
        new = STCudaKernelCall(parent=current,lineno=currentLineno,lines=currentLines)
        new._lines = currentLines
        current.append(new)
    def inParallelAccRegionAndNotRecording():
        nonlocal current
        nonlocal keepRecording
        return not keepRecording and\
            (type(current) is STAccDirective) and\
            (current.isKernelsDirective() or current.isParallelDirective())
    def AccDirective(tokens):
        nonlocal current
        nonlocal currentLines
        nonlocal currentLineno
        nonlocal keepRecording
        nonlocal doLoopCtr
        nonlocal directiveNo
        new = STAccDirective(current,currentLineno,currentLines,directiveNo)
        directiveNo = directiveNo + 1
        msg = "scanner: {}: found acc construct:\t'{}'".format(currentLineno,new.singleLineStatement())
        logging.getLogger("").info(msg) ; print(msg)
        # if end directive ascend
        if new.isEndDirective() and type(current) is STAccDirective and\
           (current.isKernelsDirective() or current.isParallelDirective()):
            ascend()
            current.append(new)
        # descend in constructs or new node
        elif new.isParallelLoopDirective() or new.isKernelsLoopDirective():
            keepRecording = True
            new = STAccLoopKernel(current,currentLineno,currentLines,directiveNo)
            new._doLoopCtrMemorised=doLoopCtr
            descend(new)  # descend also appends 
            keepRecording = True
            #print("descend into parallel loop: do loops=%d" % doLoopCtr)
        elif not new.isEndDirective() and (new.isKernelsDirective() or new.isParallelDirective()):
            descend(new)  # descend also appends 
            #print("descending into kernels or parallel construct")
        else:
           # append new directive
           current.append(new)
    def Assignment(tokens):
        nonlocal current
        nonlocal currentLines
        nonlocal currentLineno
        nonlocal singleLineStatement
        if inParallelAccRegionAndNotRecording():
            parseResult = translator.assignmentBegin.parseString(singleLineStatement)
            lvalue = translator.findFirst(parseResult,translator.TTLvalue)
            if not lvalue is None and lvalue.hasMatrixRangeArgs():
                new = STAccLoopKernel(parent=current,lineno=currentLineno,lines=currentLines)
                new._directiveLines = current._directiveLines # TODO make args or move into constructor
                new._lines          = currentLines
                current.append(new)
    
    moduleStart.setParseAction(Module_visit)
    programStart.setParseAction(Program_visit)
    functionStart.setParseAction(Function_visit)
    subroutineStart.setParseAction(Subroutine_visit)
    structureEnd.setParseAction(Structure_leave)
    
    DO.setParseAction(DoLoop_visit)
    ENDDO.setParseAction(DoLoop_leave)
 
    use.setParseAction(UseStatement)
    CONTAINS.setParseAction(PlaceHolder)
    IMPLICIT.setParseAction(PlaceHolder)
    
    declaration.setParseAction(Declaration)
    attributes.setParseAction(Attributes)
    allocated.setParseAction(Allocated)
    allocate.setParseAction(Allocate)
    deallocate.setParseAction(Deallocate)
    memcpy.setParseAction(Memcpy)
    #pointerAssignment.setParseAction(PointerAssignment)
    nonZeroCheck.setParseAction(NonZeroCheck)

    # CUDA Fortran 
    cufPragma.setParseAction(CufLoopKernel)
    cudaLibCall.setParseAction(CudaLibCall)
    cudaKernelCall.setParseAction(CudaKernelCall)

    # OpenACC
    accBegin.setParseAction(AccDirective)
    assignmentBegin.setParseAction(Assignment)

    currentFile = str(fortranFilePath)
    current._children.clear()
    
    def scanString(expressionName,expression):
        """
        These expressions might be hidden behind a single-line if.
        """
        nonlocal currentLines
        nonlocal currentLineno
        nonlocal singleLineStatement

        matched = len(expression.searchString(singleLineStatement,1))
        if matched:
           logging.getLogger("").debug("scanner::scanString\tFOUND expression '{}' in line {}: '{}'".format(expressionName,currentLineno,currentLines[0].rstrip()))
        else:
           logging.getLogger("").debug2("scanner::scanString\tdid not find expression '{}' in line {}: '{}'".format(expressionName,currentLineno,currentLines[0].rstrip()))
        return matched
    
    def tryToParseString(expressionName,expression):
        """
        These expressions might never be hidden behind a single-line if or might
        never be an argument of anoother calls.
        No need to check if comments are in the line as the first
        words of the line must match the expression.
        """
        nonlocal currentLines
        nonlocal currentLineno
        nonlocal singleLineStatement
        
        try:
           expression.parseString(singleLineStatement)
           logging.getLogger("").debug("scanner::tryToParseString\tFOUND expression '{}' in line {}: '{}'".format(expressionName,currentLineno,currentLines[0].rstrip()))
           return True
        except ParseBaseException as e: 
           logging.getLogger("").debug2("scanner::tryToParseString\tdid not find expression '{}' in line '{}'".format(expressionName,currentLines[0]))
           logging.getLogger("").debug3(str(e))
           return False
    
    pDirectiveContinuation = re.compile(r"\n[!c\*]\$\w+\&")
    pContinuation          = re.compile(r"(\&\s*\n)|(\n[!c\*]\$\w+\&)")
    with open(fortranFilePath,"r") as fortranFile:
        # 1. Handle all include statements
        lines = handleIncludeStatements(fortranFilePath,fortranFile.readlines())
        # 2. collapse multi-line statements (&)
        buffering = False
        lineStarts = []
        for lineno,line in enumerate(lines):
            # Continue buffering if multiline CUF/ACC/OMP statement
            buffering |= pDirectiveContinuation.match(line) != None
            if not buffering:
                lineStarts.append(lineno)
            if line.rstrip().endswith("&"):
                buffering = True
            else:
                buffering = False
        lineStarts.append(len(lines))
        # TODO merge this with loop above
        # 3. now go through the collapsed lines
        for i,_ in enumerate(lineStarts[:-1]):
            lineStart     = lineStarts[i]
            lineEnd       = lineStarts[i+1]
            currentLineno = lineStart
            currentLines  = lines[lineStart:lineEnd]
            
            # make lower case, replace line continuation by whitespace, split at ";"
            preprocessedLines = pContinuation.sub(" "," ".join(currentLines).lower()).split(";")
            for singleLineStatement in preprocessedLines: 
                # host code
                if "cuf" in SOURCE_DIALECTS:
                    scanString("attributes",attributes)
                    scanString("cudaLibCall",cudaLibCall)
                    scanString("cudaKernelCall",cudaKernelCall)
      
                # scan for more complex expressions first      
                scanString("assignmentBegin",assignmentBegin)
                scanString("memcpy",memcpy)
                scanString("allocated",allocated)
                scanString("deallocate",deallocate) 
                scanString("allocate",deallocate) 
                scanString("nonZeroCheck",nonZeroCheck)
                #scanString("cpp_ifdef",cpp_ifdef)
                #scanString("cpp_defined",cpp_defined)
                
                # host/device environments  
                #tryToParseString("callEnd",callEnd)
                if not tryToParseString("structureEnd|ENDDO",structureEnd|ENDDO):
                    tryToParseString("use|CONTAINS|IMPLICIT|declaration|accBegin|cufPragma|DO|moduleStart|programStart|functionStart|subroutineStart",\
                       use|CONTAINS|IMPLICIT|declaration|accBegin|cufPragma|DO|moduleStart|programStart|functionStart|subroutineStart)
                if keepRecording:
                   try:
                      current._lines += currentLines
                   except Exception as e:
                      logging.getLogger("").error("While parsing file {}".format(currentFile))
                      raise e
    assert type(current) is STRoot
    return current

def postProcess(stree,hipModuleName):
    """
    Add use statements as well as handles plus their creation and destruction for certain
    math libraries.
    """
    global CUBLAS_VERSION 
    # insert use kernel statements at appropriate point
    def isLoopKernel(child):
        return isinstance(child,STLoopKernel) or\
               (type(child) is STSubroutine and child.isDeviceSubroutine())
    kernels = stree.findAll(filter=isLoopKernel, recursively=True)
    for kernel in kernels:
         stnode = kernel._parent.findFirst(filter=lambda child: not child._included and type(child) in [STUseStatement,STDeclaration,STPlaceHolder])
         assert not stnode is None
         indent = " "*(len(stnode.lines()[0]) - len(stnode.lines()[0].lstrip()))
         stnode._preamble.add("{0}use {1}\n".format(indent,hipModuleName))
    # cublas_v1 detection
    if CUBLAS_VERSION is 1:
        def hasCublasCall(child):
            return type(child) is STCudaLibCall and child.hasCublas()
        cublasCalls = stree.findAll(filter=hasCublasCall, recursively=True)
        #print(cublasCalls)
        for call in cublasCalls:
            begin = call._parent.findLast(filter=lambda child : type(child) in [STUseStatement,STDeclaration])
            indent = " "*(len(begin.lines()[0]) - len(begin.lines()[0].lstrip()))
            begin._epilog.add("{0}type(c_ptr) :: hipblasHandle = c_null_ptr\n".format(indent))
            #print(begin._lines)       
 
            localCublasCalls = call._parent.findAll(filter=hasCublasCall, recursively=False)
            first = localCublasCalls[0]
            indent = " "*(len(first.lines()[0]) - len(first.lines()[0].lstrip()))
            first._preamble.add("{0}hipblasCreate(hipblasHandle)\n".format(indent))
            last = localCublasCalls[-1]
            indent = " "*(len(last.lines()[0]) - len(last.lines()[0].lstrip()))
            last._epilog.add("{0}hipblasDestroy(hipblasHandle)\n".format(indent))
    # acc detection
    directives = stree.findAll(filter=lambda node: isinstance(node,STAccDirective), recursively=True)
    for directive in directives:
         stnode = directive._parent.findFirst(filter=lambda child : type(child) in [STUseStatement,STDeclaration,STPlaceHolder])
         if not stnode is None:
             indent = " "*(len(stnode.lines()[0]) - len(stnode.lines()[0].lstrip()))
             stnode._preamble.add("{0}use iso_c_binding\n{0}use {1}\n".format(indent,"gpufort_acc_runtime"))
 
def groupObjects(stree):
    """ 
    Groups object tree nodes and puts each group into a map that is indexed by the line number of the first node in a group.
    :return: a dict mapping line numbers to groups
    :rtype: dict
    :note: Must be called before declarations from other modules are loaded
    """
    def transformOneByOne(stnode):
        return type(stnode) in  [STDeclaration,STUseStatement,STPlaceHolder,STSubroutine,STAccDirective] or isinstance(stnode,STLoopKernel)
    groups = [ MatchAllGroup() ]
    def descend(curr):
        for stnode in curr._children:
            logging.getLogger("").debug("scanner:groubObjects(...):\t{0}".format("{}-{}: ".format(stnode._lineno,stnode._lineno+len(stnode.lines()))+str(stnode)))
            if not stnode._included and stnode.considerInSource2SourceTranslation():
                # insert new group if necessary
                if not groups[-1].borders(stnode): 
                    if transformOneByOne(stnode): # TODO two groups. One contains data, the other can match anything
                        groups.append(OneByOneGroup())
                    else:
                        groups.append(MatchAllGroup())
                else:
                    if type(groups[-1]) is MatchAllGroup and transformOneByOne(stnode):
                        groups.append(OneByOneGroup())
                    elif type(groups[-1]) is OneByOneGroup and not transformOneByOne(stnode):
                        groups.append(MatchAllGroup())
                groups[-1].add(stnode)
            descend(stnode)
    descend(stree)      
    groupMap = {}
    for group in groups:
         groupMap[group._minLineno] = group
    return groupMap