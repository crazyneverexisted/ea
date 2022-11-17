#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
import os,sys
import time
import unittest
import addtoplevelpath
import inspect
import cProfile,pstats,io

from gpufort import translator
from gpufort import indexer

print("Running test '{}'".format(os.path.basename(__file__)),end="",file=sys.stderr)

PROFILING_ENABLE = False

scope = None

semantics = translator.semantics.Semantics()

class TestSemantics(unittest.TestCase):
    def setUp(self):
        global PROFILING_ENABLE
        self.started_at = time.time()
        if PROFILING_ENABLE:
            self.profiler = cProfile.Profile()
            self.profiler.enable()
    def tearDown(self):
        elapsed = time.time() - self.started_at
        print('{} ({}s)'.format(self.id(), round(elapsed, 9)))
        if PROFILING_ENABLE:
            self.profiler.disable() 
            s = io.StringIO()
            sortby = 'cumulative'
            stats = pstats.Stats(self.profiler, stream=s).sort_stats(sortby)
            stats.print_stats(10)
            print(s.getvalue())
    def test_00_do_nothing(self):
        pass
    def test_01_create_scope(self):
        global scope
        scope = indexer.scope.create_scope_from_declaration_list("""\
        implicit none
        integer, parameter :: m = 2, n = 3, k = 4
        integer :: i,j,k
        integer :: A(m),B(m,n),C(m,n,k)
        integer(c_long) :: D(m),E(m,n),F(m,n,k)
        real :: alpha,beta,gamma
        real :: X(m),Y(m,n),Z(m,n,k)
        real(c_double) :: U(m),V(m,n),W(m,n,k)

        type mytype_t
          real :: X(m),Y(m,n),Z(m,n,k)
        end type
        
        type(mytype_t) :: mytypes(10)
        """)
    
    parse_arith_expr_testdata = [
      "1", 
      "A(i) + B(i,j)",
      "A(i) + B(i,j) - C(i,j,k)",
      "A(i) + B(i,j)*C(i,j,k)",
      "A(i) + B(i,j)*C(i,j,k) + A(k)",
      "C(i,j,k)*(A(i) + B(i,j)*C(i,j,k) + A(k))",
      # rank > 0
      "X(:) + alpha",
      "A(:) + B(1,:)",
      "X(:) + Y(1,:) + Z(1,n,:)",
      "Y + Z(1,:,:)",
      "V + W(1,:,:)",
      "V + Z(1,:,:)", # mix float and double
    ]       
    
    parse_arith_expr_parse_results = [] # will be filled by a test
    
    resolve_arith_expr_results = [
      ('integer', 4, 0),
      ('integer', 4, 0),
      ('integer', 4, 0),
      ('integer', 4, 0),
      ('integer', 4, 0),
      ('integer', 4, 0),
      ('real', 4, 1),
      ('integer', 4, 1),
      ('real', 4, 1),
      ('real', 4, 2),
      ('real', 8, 2),
      ('real', 8, 2),
    ]

    def test_02_parse_arith_expr(self):
        for i,test in enumerate(TestSemantics.parse_arith_expr_testdata):
            ttarithexpr = translator.tree.grammar.arith_expr.parseString(
              test,parseAll=True
            )[0]
            TestSemantics.parse_arith_expr_parse_results.append(ttarithexpr)
    
    def test_03_resolve_arith_expr(self):
        for i,test in enumerate(TestSemantics.parse_arith_expr_testdata):
            ttarithexpr = TestSemantics.parse_arith_expr_parse_results[i]
            #print(ttarithexpr.fstr())
            semantics.resolve_arith_expr(ttarithexpr,scope)
            result_tuple = (ttarithexpr.type,
                      ttarithexpr.bytes_per_element,
                      ttarithexpr.rank)
            self.assertEqual(TestSemantics.resolve_arith_expr_results[i],result_tuple)

    parse_rvalue_testdata = [
      # 1d
      "X",
      "X(1)",
      "X(:)",
      "X(1:)",
      "X(1:5)",
      "X(1:5:2)",
      # 2d
      "Y",
      "Y(1,1)",
      "Y(:,:)",
      "Y(:,1)",
      "Y(1:,1)",
      "Y(1:5,1)",
      "Y(:,:5)",
      "Y(1,:5)",
      "Y(1:,:5)",
      "Y(1:5,:5)",
      # derived_type expressions 
      "mytypes(i)%x(1)",
      "mytypes(i)%x(:)",
      "mytypes(:)%x(1)",
    ]
    
    parse_rvalue_parse_results = [] # will be filled by a test
    
    # scalar|array|contiguous array|full array
    resolve_rvalue_results = [
      (False, True, True, True),
      (True, False, False, False),
      (False, True, True, True),
      (False, True, True, False),
      (False, True, True, False),
      (False, True, False, False),
      (False, True, True, True),
      (True, False, False, False),
      (False, True, True, True),
      (False, True, True, False),
      (False, True, True, False),
      (False, True, True, False),
      (False, True, True, False),
      (False, True, False, False),
      (False, True, False, False),
      (False, True, False, False),
      (True, False, False, False),
      (False, True, True, True),
      (False, True, False, False),
    ]
    
    def test_04_parse_rvalue(self):
        for i,test in enumerate(TestSemantics.parse_rvalue_testdata):
            ttrvalue = translator.tree.grammar.rvalue.parseString(
              test,parseAll=True
            )[0]
            TestSemantics.parse_rvalue_parse_results.append(ttrvalue)

    def test_05_resolve_rvalue(self):
        for i,test in enumerate(TestSemantics.parse_rvalue_testdata):
            ttrvalue = TestSemantics.parse_rvalue_parse_results[i] 
            semantics.resolve_arith_expr(ttrvalue,scope)
            result_tuple = (
              ttrvalue.is_scalar,
              ttrvalue.is_array,
              ttrvalue.is_contiguous_array,
              ttrvalue.is_full_array,
            )
            print(test)
            print(result_tuple)
            self.assertEqual(
              TestSemantics.resolve_rvalue_results[i],
              result_tuple
            )
    
    def test_06_resolve_function_call(self):
        testdata = [
          "real(1)",
          #"real(1,8)",
          #"real(j,kind=8)",
        ]

        for i,test in enumerate(testdata):
            ttrvalue = translator.tree.grammar.rvalue.parseString(
              test,parseAll=True
            )[0]
            semantics.resolve_arith_expr(ttrvalue,scope)
            result_tuple = (
              ttrvalue.is_function_call,
              ttrvalue.is_elemental_function_call,
              ttrvalue.is_converter_call,
            )
            #print(test)
            print(result_tuple)
            #self.assertEqual(
            #  TestSemantics.resolve_rvalue_results[i],
            #  result_tuple
            #)

if __name__ == '__main__':
    unittest.main() 
