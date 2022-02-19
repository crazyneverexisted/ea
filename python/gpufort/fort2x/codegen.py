# SPDX-License-Identifier: MIT
# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
import os
import copy
import logging
import abc

from gpufort import translator
from gpufort import indexer
from gpufort import scanner
from gpufort import util

from . import filegen
from . import opts


class CodeGenerator(abc.ABC):
    """Modify a scanner tree and generate Fortran and C/C++ code from it."""

    def __init__(self, stree, index, **kwargs):
        r"""Constructor.
        :param stree: Scanner tree created by GPUFORT's scanner component.
        :param index: Index data structure created by GPUFORT's indexer component.
        
        :param \*\*kwargs: See below.
        
        :Keyword Arguments:

        * *kernels_to_convert* (`list`):
            Filter the kernels to convert to C++ by their name or their id. Pass ['*'] 
            to extract all kernels [default: ['*']]
        * *cpp_file_preamble* (`str`):
            A preamble to write at the top of the files produced by the C++ generators
            that can be created by this class [default: .opts.cpp_file_preamble].
        * *cpp_file_ext* (`str`):
            File extension for the generated C++ files [default: .opts.cpp_file_ext].
        * *default_modules* (`list`):
            Default modules to use by any interface or modified Fortran module, program, or procedure. [default: .opts.fortran_default_modules].
        * *default_includes* (`list`):
            Default includes for generated C++ files. [default: .opts.cpp_default_includes].
        * *fortran_module_suffix* (`str`):
            Suffix for generated Fortran modules [default: .opts.fortran_module_suffix].
        """
        self.stree = stree
        self.index = index
        util.kwargs.set_from_kwargs(self, "kernels_to_convert", ["*"],
                                    **kwargs)
        util.kwargs.set_from_kwargs(self, "cpp_file_preamble",
                                    opts.cpp_file_preamble, **kwargs)
        util.kwargs.set_from_kwargs(self, "cpp_file_ext", opts.cpp_file_ext,
                                    **kwargs)
        util.kwargs.set_from_kwargs(self, "fortran_module_suffix",
                                    opts.fortran_module_suffix, **kwargs)
        util.kwargs.set_from_kwargs(self, "default_modules",
                                    opts.fortran_default_modules, **kwargs)
        util.kwargs.set_from_kwargs(self, "default_includes",
                                    opts.cpp_default_includes, **kwargs)
        # adjusted by subclasses
        #
        self.cpp_filegen = filegen.CppFileGenerator(
            prolog=self.cpp_file_preamble)
        self.cpp_filegens_per_module = []
        self.fortran_modulegens = []
        self._traversed = False

    @staticmethod
    def _indent(text, indent):
        return "\n".join([indent + line for line in text.splitlines()])

    @staticmethod
    def _create_cpp_guard(cpp_file_name):
        result = ""
        for c in cpp_file_name:
            result += c.upper() if c.isalnum() else "_"
        return "{}".format(result)

    @staticmethod
    def _fort2x_node_name(stnode):
        """Name of module file generated by fort2x for module/program/procedure."""
        return stnode.tag().replace(":", "_")

    def _create_includes_from_used_modules(self, irecord):
        """Create include statement for a module's/subprogram's used modules that are present in the self.index."""
        used_modules = [irecord["name"] for irecord in irecord["used_modules"]]
        includes = []
        for imodule in self.index:
            if imodule["name"] in used_modules:
                includes.append("".join([imodule["name"], self.cpp_file_ext]))
        return includes

    def _consider_kernel(self, stkernel):
        if not len(self.kernels_to_convert):
            return False
        else:
            condition1 = not stkernel.ignore_in_s2s_translation
            condition2 = \
                    self.kernels_to_convert[0] == "*" or\
                    stkernel.min_lineno() in self.kernels_to_convert or\
                    stkernel.kernel_name() in self.kernels_to_convert
            return condition1 and condition2

    def _loop_kernel_filter(self, child):
        return isinstance(
            child, scanner.tree.STLoopNest) and self._consider_kernel(child)

    def _device_procedure_filter(self, stprocedure):
        return isinstance(stprocedure, scanner.tree.STProcedure) and\
               stprocedure.must_be_available_on_device() and consider_kernel(stprocedure)

    def _make_module_dicts(self, module_names):
        return [{"name": mod, "only": []} for mod in module_names]

    def _render_derived_types(self, itypes, cpp_filegen, fortran_modulegen):
        pass

    def _render_loop_nest(self, stkernel, cpp_filegen, fortran_modulegen):
        pass

    def _render_device_procedure(self, stnode, cpp_filegen, fortran_modulegen):
        pass

    def _modify_stcontainer(self, stcontainer, fortran_modulegen):
        """This routine performs the following operations:
        - Add default GPUFORT use statements to the container node.
        - Add rendered derived types and interfaces after the declaration section of the
              container node.
        - Add rendered routines before end statement.
        - Add "contains" (if not present) to end statement.
        """
        # add GPUFORT use statements
        indent_parent = stcontainer.first_line_indent()
        indent = indent_parent + " "*2
        if len(fortran_modulegen.rendered_types):
            for mod in self.default_modules:
                stcontainer.add_to_epilog("{}use {}".format(indent, mod),
                                          prepend=True)
        # types and interfaces
        stlastdeclnode = stcontainer.last_entry_in_decl_list()
        for snippet in fortran_modulegen.rendered_types:
            stlastdeclnode.add_to_epilog(CodeGenerator._indent(
                snippet, indent))
        for snippet in fortran_modulegen.rendered_interfaces:
            stlastdeclnode.add_to_epilog(CodeGenerator._indent(
                snippet, indent))
        # routines
        stend = stcontainer.end_statement()
        #add_to_prolog(self,line,prepend=False):
        for snippet in fortran_modulegen.rendered_routines:
            stend.add_to_prolog(CodeGenerator._indent(snippet, indent))
        if not stcontainer.has_contains_statement():
            stend.add_to_prolog(CodeGenerator._indent("contains",
                                                      indent_parent),
                                prepend=True)

    def _traverse_scanner_tree(self):
        """Traverse scanner tree and call subcalls render methods.
        """
        cpp_filegen = None
        fortran_modulegen = None

        def traverse_node_(stnode):
            """Traverse and modify scanner tree, create C/C++ file generators.
            :param stnode: A scanner tree node
            :note: Recursive algorithm.
            """
            nonlocal cpp_filegen
            nonlocal fortran_modulegen
            # main
            if isinstance(stnode, scanner.tree.STRoot):
                for stchildnode in stnode.children:
                    traverse_node_(stchildnode)
            elif self._loop_kernel_filter(stnode):
                self._render_loop_nest(stnode, cpp_filegen, fortran_modulegen)
            elif self._device_procedure_filter(
                    stnode
            ): # handle before STProcedure (without attributes) is handled
                inode = next((irecord for irecord in self.index
                              if irecord["name"] == stnode_name), None)
                self._render_device_procedure(stnode, inode, cpp_filegen,
                                              fortran_modulegen)
            elif isinstance(stnode,
                            (scanner.tree.STProgram, scanner.tree.STModule,
                             scanner.tree.STProcedure)):
                stnode_name = stnode.name.lower()
                if isinstance(stnode.parent, scanner.tree.STRoot):
                    inode = next((irecord for irecord in self.index
                                  if irecord["name"] == stnode_name), None)
                    cpp_file_name = "{}{}".format(
                        CodeGenerator._fort2x_node_name(stnode),
                        self.cpp_file_ext)
                    cpp_filegen = filegen.CppFileGenerator(
                        guard=CodeGenerator._create_cpp_guard(cpp_file_name),
                        prolog=self.cpp_file_preamble,
                        default_includes=self.default_includes)
                    fortran_modulegen = filegen.FortranModuleGenerator(
                        name=inode["name"] + opts.fortran_module_suffix,
                        default_modules=self._make_module_dicts(
                            self.default_modules))
                else:
                    assert isinstance(stnode, scanner.tree.STProcedure)
                    inode = stnode.index_record
                    if isinstance(stnode.parent, scanner.tree.STModule):
                        fortran_modulegen = filegen.FortranModuleGenerator(
                            name=inode["name"] + opts.fortran_module_suffix,
                            default_modules=self._make_module_dicts(
                                self.default_modules))
                if inode == None:
                    util.logging.log_error(LOG_PREFIX,\
                                            "traverse_scanner_tree",\
                                            "could not find self.index record for scanner tree node '{}'.".format(stnode_name))
                    sys.exit() # TODO add error code

                cpp_filegen.includes += self._create_includes_from_used_modules(
                    inode)

                # types
                itypes = inode["types"]
                if len(itypes) and isinstance(
                        stnode.parent,
                    (scanner.tree.STRoot, scanner.tree.STModule)):
                    # In order to create derived type copy routines,
                    # the scope of the code section that declares the type must
                    # be available to the newly created subroutines.
                    # Due to the below Fortran limitations
                    # * 1 nested contains section in program/procedure
                    # * up to 2 nested contains sections in module (one in module + one in procedure)
                    # the parent must therefore either be a root node or module node.
                    self._render_derived_types(itypes, cpp_filegen,
                                               fortran_modulegen)
                elif len(itypes):
                    util.logging.log_warning(LOG_PREFIX,\
                                              "traverse_scanner_tree",\
                                              "won't create interoperable type for derived types declared in procedure '{}'.".format(stnode_name))

                # traverse children
                for stchildnode in stnode.children:
                    traverse_node_(stchildnode)

                # finalize
                if isinstance(stnode.parent,(scanner.tree.STRoot,scanner.tree.STModule)) and\
                   fortran_modulegen.stores_any_code():
                    # Directly modify Fortran tree with new definitions.
                    self._modify_stcontainer(stnode, fortran_modulegen)
                if isinstance(stnode.parent, scanner.tree.STRoot) and\
                   fortran_modulegen.stores_any_code():
                    # module generator can be used to generate standalone module (files).
                    self.fortran_modulegens.append(fortran_modulegen)
                if isinstance(stnode, scanner.tree.STModule): #
                    self.cpp_filegen.includes.append(cpp_file_name)
                    self.cpp_filegens_per_module.append((
                        cpp_file_name,
                        cpp_filegen,
                    ))
                else:
                    self.cpp_filegen.merge(cpp_filegen)

        traverse_node_(self.stree)
        traversed = True

    def run(self):
        """Generates one C++ file ('main C++ file') for the non-module program units
        in the Fortran file plus one C++ file per each of the modules in the Fortran 
        file. The main C++ file includes the per-module C++ files.
        :note: Always creates the main C++ file even if no code was generated
               to always have the same output.
        :see: cpp_filegen, cpp_filegens_per_module, fortran_modulegens
        """
        if not self._traversed:
            self._traverse_scanner_tree()

    def write_cpp_files(self, main_cpp_file_path):
        """Writes one C++ file ('main C++ file') for the non-module program units
        in the Fortran file plus one C++ file per each of the modules in the file.
        The main C++ file includes the per-module C++ files.
        
        :param str main_cpp_file_path: File name for the main C++ file.
        
        :return: Paths to all generated files (list of strings).
        :rtype: list
       
        :note: Always creates the main C++ file even if no code was generated
               to always have the same output.
        """
        main_cpp_file_name = os.path.basename(main_cpp_file_path)
        output_dir = os.path.dirname(main_cpp_file_path)
        if not self._traversed:
            self._traverse_scanner_tree()
        # main file
        self.cpp_filegen.guard = CodeGenerator._create_cpp_guard(
            main_cpp_file_name)
        self.cpp_filegen.generate_file(main_cpp_file_path)
        #
        paths = [main_cpp_file_path]
        #
        for pair in self.cpp_filegens_per_module:
            cpp_file_name, cpp_filegen = pair
            cpp_file_path = os.path.join(output_dir, cpp_file_name)
            cpp_filegen.generate_file(cpp_file_path)
            paths.append(cpp_file_path)
        return paths