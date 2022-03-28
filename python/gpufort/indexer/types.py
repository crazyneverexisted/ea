# SPDX-License-Identifier: MIT
# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved.
import copy

from gpufort import translator

__UNKNOWN = "UNKNOWN"

EMPTY_TYPE = {"name": __UNKNOWN, "variables": []}

EMPTY_PROCEDURE = {
    "kind": __UNKNOWN,
    "name": __UNKNOWN,
    "result_name": __UNKNOWN,
    "attributes": [],
    "dummy_args": [],
    "variables": [],
    "procedures": [],
    "used_modules": []
}

EMPTY_SCOPE = {"tag": "", "types": [], "variables": [], "procedures": []}
SCOPE_ENTRY_TYPES = ["types", "variables", "procedures"]

EMPTY_VAR = {
        "name"   : __UNKNOWN,
        "f_type" : __UNKNOWN,
        "kind"   : __UNKNOWN,
        # TODO bytes per element can be computed on the fly
        "bytes_per_element" : __UNKNOWN,
        "c_type" : __UNKNOWN,
        "qualifiers" : [],
        # ACC/OMP
        "declare_on_target" : False,
        # arrays
        "bounds" : [],
        "rank"   : -1,
        # parse rhs if necessary
        "rhs" : __UNKNOWN,
}

def create_index_var(f_type,kind,name,qualifiers=[],bounds=[],rhs=None):
    ivar = copy.copy(EMPTY_VAR)
    # basic
    ivar["name"]   = name
    ivar["f_type"] = f_type
    ivar["kind"]   = kind
    # TODO bytes per element can be computed on the fly
    ivar["bytes_per_element"] = translator.num_bytes(f_type, kind, default=None)
    if f_type == "type":
        ivar["c_type"] = ivar["kind"] 
    elif f_type == "character":
        ivar["c_type"] = "char"
        # TODO more carefully check if len or kind is specified for characters
    elif f_type != "character": 
        ivar["c_type"] = translator.convert_to_c_type(f_type, kind, "TODO unknown")
    ivar["qualifiers"] = qualifiers
    # arrays
    ivar["bounds"] = bounds
    ivar["rank"]   = len(bounds)
    # handle parameters
    #ivar["value"] = None # TODO parse rhs if necessary
    ivar["rhs"] = rhs
    return ivar