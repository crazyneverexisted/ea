# SPDX-License-Identifier: MIT
# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
from gpufort import translator
from gpufort import util

from ... import opts

from .. import backends

from . import accbackends
from . import accnodes

dest_dialects = ["omp"]
backends.supported_destination_dialects.update(set(dest_dialects)) 

class Acc2Omp(accbackends.AccBackendBase):

    def transform(self,
                  joined_lines,
                  joined_statements,
                  statements_fully_cover_lines,
                  index=[]):

        snippet = joined_statements
        try:

            def repl(parse_result):
                return parse_result.omp_f_str(), True
            result,_ = util.pyparsing.replace_first(snippet,\
                     translator.tree.grammar.acc_simple_directive,\
                     repl)
            return result, True
        except Exception as e:
            util.logging.log_exception(
                opts.log_prefix, "Acc2Omp.transform",
                "failed parse directive " + str(snippet))


class AccComputeConstruct2Omp(accbackends.AccBackendBase):

    def transform(self,
                  joined_lines,
                  joined_statements,
                  statements_fully_cover_lines,
                  index=[]):
        parent_tag = self.stnode.parent.tag()
        scope      = indexer.scope.create_scope(index, parent_tag)
        ttloopnest = stloopkernel.parse_result 
        
        arrays       = translator.analysis.arrays_in_subtree(ttloopnest, scope)
        inout_arrays = translator.analysis.inout_arrays_in_subtree(ttloopnest, scope)

        snippet = joined_lines if statements_fully_cover_lines else joined_statements
        return translator.codegen.translate_loopnest_to_omp(snippet, ttloopnest, inout_arrays_in_body, arrays_in_body), True

accnodes.STAccDirective.register_backend(dest_dialects,Acc2Omp())
accnodes.STAccComputeConstruct.register_backend(dest_dialects,AccComputeConstruct2Omp())