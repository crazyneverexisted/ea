{# SPDX-License-Identifier: MIT #}
{# Copyright (c) 2020-2022 Advanced Micro Devices, Inc. All rights reserved. #}
{########################################################################################}
{%- macro render_set_fptr_lower_bound(fptr,array,rank) -%}
{########################################################################################}
{% set rank_ub=rank+1 %}
{{fptr}}(&
{% for i in range(1,rank_ub) %}
  lbound({{array}},{{i}}):{{ "," if not loop.last else ")" }}&
{% endfor %}
    => {{fptr}}
{%- endmacro  -%}
{#######################################################################################}
{% macro render_interface(interface_name,has_backend=False) %}
{#######################################################################################}
interface {{interface_name}}
  module procedure &
{% if has_backend %}
    {{interface_name}}_b, &
{% endif %}
{% for tuple in datatypes %}
{%   for dims in dimensions %}
{%     set name = interface_name+"_" + tuple[0] + "_" + dims|string %}
    {{name}}{{",&\n" if not loop.last}}{% endfor %}{{ ",&" if not loop.last}}
{% endfor %}
end interface
{% endmacro %}
{#######################################################################################}
{% macro render_interface_v2(routine,datatypes) %}
{#######################################################################################}
interface gpufortrt_{{routine}}
  module procedure :: gpufortrt_{{routine}}_b
{%   for tuple in datatypes -%}
  module procedure :: gpufortrt_{{routine}}_{{tuple[0]}}_scal
  module procedure :: gpufortrt_{{routine}}_{{tuple[0]}}_arr
{%   endfor %}{# datatypes #}
end interface
{% endmacro %}
{########################################################################################}
{%- macro render_map_routines(datatypes) -%}
{# NOTE: type(*) is a Fortran 2018 feature.
{########################################################################################}
{% for clause in ["present","create","copyin","copy","copyout"] -%}
{%   set routine = "gpufortrt_map_" + clause %}
function {{routine}}_b(hostptr,num_bytes,never_deallocate) result(retval)
  use iso_c_binding
  use gpufortrt_types
  implicit none
  type(c_ptr),intent(in) :: hostptr
  integer(c_size_t),intent(in),optional :: num_bytes 
  logical,intent(in),optional :: never_deallocate
  !
  type(mapping_t) :: retval
  !
  call gpufortrt_mapping_init(retval,c_loc(hostptr),num_bytes,&
         gpufortrt_map_kind_{{clause}},never_deallocate)
end function
{%   for tuple in datatypes -%}
!> \note never_deallocate only has effect on create,copyin,copyout, and copy mappings.
function {{routine}}_{{tuple[0]}}_scal(hostptr,never_deallocate) result(retval)
  use iso_c_binding
  use gpufortrt_types
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  logical,intent(in),optional :: never_deallocate
  !
  type(mapping_t) :: retval
  !
  retval = {{routine}}_b(c_loc(hostptr),int({{tuple[1]}},c_size_t),never_deallocate)
end function

!> \note never_deallocate only has effect on create,copyin,copyout, and copy mappings.
function {{routine}}_{{tuple[0]}}_arr(hostptr,num_elements,never_deallocate) result(retval)
  use iso_c_binding
  use gpufortrt_types
  implicit none
  {{tuple[2]}},dimension(*),target,intent(in) :: hostptr
  integer,intent(in) :: num_elements
  logical,intent(in),optional :: never_deallocate
  !
  type(mapping_t) :: retval
  !
  retval = {{routine}}_b(c_loc(hostptr),int({{tuple[1]}},c_size_t)*num_elements,never_deallocate)
end function
{%   endfor -%} 
{% endfor -%} 
{%- endmacro -%}
{#######################################################################################}
{% macro render_basic_map_and_lookup_routines() %}
{#######################################################################################}
{% for clause in ["create","copyin","copy","copyout"] %}
!> Map and directly return the corresponding deviceptr.
function gpufortrt_{{clause}}_b(hostptr,num_bytes,never_deallocate,&
    async_arg,ctr_to_update) result(deviceptr)
  use iso_c_binding
  implicit none
  type(c_ptr),intent(in) :: hostptr
  integer(c_size_t),intent(in) :: num_bytes
  logical,intent(in),optional :: never_deallocate
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg 
  integer(kind(gpufortrt_counter_none)),intent(in),optional :: ctr_to_update
  !
  type(c_ptr) :: deviceptr
  !
  interface
    subroutine gpufortrt_{{clause}}_c_impl(hostptr,num_bytes,never_deallocate,ctr_to_update) &
        bind(c,name="gpufortrt_{{clause}}") result(deviceptr)
      type(c_ptr),value,intent(in) :: hostptr
      integer(c_size_t),value,intent(in) :: num_bytes
      logical(c_bool),intent(in),optional :: never_deallocate
      integer(kind(gpufortrt_counter_none)),value,intent(in) :: ctr_to_update
    end subroutine
    subroutine gpufortrt_{{clause}}_async_c_impl(hostptr,num_bytes,never_deallocate,async_arg,ctr_to_update) &
        bind(c,name="gpufortrt_{{clause}}_async") result(deviceptr)
      type(c_ptr),value,intent(in) :: hostptr
      integer(c_size_t),value,intent(in) :: num_bytes
      logical(c_bool),intent(in),optional :: never_deallocate
      integer(gpufortrt_handle_kind),value,intent(in) :: async_arg
      integer(kind(gpufortrt_counter_none)),value,intent(in) :: ctr_to_update
    end subroutine
  end interface
  !
  integer(kind(gpufortrt_counter_none)) :: opt_ctr_to_update
  !
  opt_ctr_to_update = gpufortrt_counter_none
  if ( present(ctr_to_update) ) opt_ctr_to_update = ctr_to_update
  if ( present(async_arg) ) then
    deviceptr = gpufortrt_{{clause}}_async_c_impl(hostptr,num_bytes,async_arg,&
        opt_ctr_to_update)
  else
    deviceptr = gpufortrt_{{clause}}_c_impl(hostptr,num_bytes,&
        opt_ctr_to_update)
  endif
end function
{% endfor %}
{% endmacro %}
{#######################################################################################}
{% macro render_specialized_map_and_lookup_routines(datatypes) %}
{#######################################################################################}
{% for clause in ["create","copyin","copy","copyout"] %}
{%   for tuple in datatypes -%}
!> Map and directly return the corresponding deviceptr.
!> (Specialized version for Fortran scalar arguments)
function gpufortrt_{{clause}}_{{tuple[0]}}_scal(hostptr,never_deallocate,async_arg,ctr_to_update) result(deviceptr)
  use iso_c_binding
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  logical,intent(in),optional :: never_deallocate
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg 
  integer(kind(gpufortrt_counter_none)),intent(in),optional :: ctr_to_update
  !
  type(c_ptr) :: deviceptr
  !
  deviceptr = gpufortrt_{{clause}}_b(c_loc(hostptr),int({{tuple[1]}},kind=c_size_t),&
                                     never_deallocate,async_arg,ctr_to_update)
end function

!> Map and directly return the corresponding deviceptr.
!> (Specialized version for Fortran array arguments)
function gpufortrt_{{clause}}_{{tuple[0]}}_arr(hostptr,num_elements,&
    never_deallocate,async_arg,ctr_to_update) result(deviceptr)
  use iso_c_binding
  implicit none
  {{tuple[2]}},dimension(*),target,intent(in) :: hostptr
  integer,intent(in) :: num_elements
  logical,intent(in),optional :: never_deallocate
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg 
  integer(kind(gpufortrt_counter_none)),intent(in),optional :: ctr_to_update
  !
  type(c_ptr) :: deviceptr
  !
  deviceptr = gpufortrt_{{clause}}_b(c_loc(hostptr),int(num_elements,kind=c_size_t)*int({{tuple[1]}},kind=c_size_t),&
                                     never_deallocate,async_arg,ctr_to_update)
end function
{%   endfor %}{# datatypes #}
{% endfor %}{# clause #}
{% endmacro %}
{#######################################################################################}
{% macro render_specialized_present_routines(datatypes) %}
{#######################################################################################}
{% for tuple in datatypes -%}
function gpufortrt_present_{{tuple[0]}}_scal(hostptr,ctr_to_update) result(deviceptr)
  use iso_c_binding
  use gpufortrt_auxiliary
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  integer(kind(gpufortrt_counter_none)),intent(in),optional :: ctr_to_update
  !
  type(c_ptr) :: deviceptr
  !
  integer(kind(gpufortrt_counter_none)) :: opt_ctr_to_update
  !
  opt_ctr_to_update = gpufortrt_counter_none
  deviceptr = gpufortrt_present_b(c_loc(hostptr),int({{tuple[1]}},kind=c_size_t),&
                                  opt_ctr_to_update)
end function

function gpufortrt_present_{{tuple[0]}}_arr(hostptr,num_elements,ctr_to_update) result(deviceptr)
  use iso_c_binding
  use gpufortrt_auxiliary
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  integer(c_int),intent(in) :: num_elements
  integer(kind(gpufortrt_counter_none)),intent(in),optional :: ctr_to_update
  !
  type(c_ptr) :: deviceptr
  !
  integer(kind(gpufortrt_counter_none)) :: opt_ctr_to_update
  !
  opt_ctr_to_update = gpufortrt_counter_none
  deviceptr = gpufortrt_present_b(c_loc(hostptr),int({{tuple[1]}},kind=c_size_t)*num_elements,&
                                  opt_ctr_to_update)
end function
{% endfor %}{# datatypes #}
{#######################################################################################}
{% macro render_map_interfaces(datatypes) %}
{#######################################################################################}
{% for clause in ["present","create","copyin","copy","copyout"] %}
{{ render_interface_v2("map_"+clause,datatypes) }}
{% endmacro %}
{#######################################################################################}
{% macro render_map_and_lookup_interfaces(datatypes) %}
{#######################################################################################}
{% for clause in ["present","create","copyin","copy","copyout"] %}
{{ render_interface_v2(clause,datatypes) }}
{% endmacro %}
{#######################################################################################}
{% macro render_basic_update_routine(update_kind) %}
{#######################################################################################}
subroutine gpufortrt_{{update_kind}}_b(hostptr,num_bytes,condition,if_present,async_arg)
  use iso_c_binding
  implicit none
  type(c_ptr),intent(in) :: hostptr
  integer(c_size_t),intent(in),optional :: num_bytes
  logical,intent(in),optional :: condition, if_present
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg
  !
  interface
    subroutine gpufortrt_{{update_kind}}_c_impl(hostptr,condition,if_present) &
            bind(c,name="gpufortrt_update_host")
      type(c_ptr),value,intent(in)     :: hostptr
      logical(c_bool),value,intent(in) :: condition, if_present
    end subroutine
    subroutine gpufortrt_{{update_kind}}_section_c_impl(hostptr,num_bytes,condition,if_present) &
            bind(c,name="gpufortrt_{{update_kind}}_section")
      type(c_ptr),value,intent(in)       :: hostptr
      integer(c_size_t),value,intent(in) :: num_bytes
      logical(c_bool),value,intent(in)   :: condition, if_present
    end subroutine
    subroutine gpufortrt_{{update_kind}}_async_c_impl(hostptr,condition,if_present,async_arg) &
            bind(c,name="gpufortrt_{{update_kind}}_async")
      type(c_ptr),value,intent(in)     :: hostptr
      logical(c_bool),value,intent(in) :: condition, if_present
      integer(c_int),value,intent(in)  :: async_arg
    end subroutine
    subroutine gpufortrt_{{update_kind}}_section_async_c_impl(hostptr,num_bytes,condition,if_present,async_arg) &
            bind(c,name="gpufortrt_{{update_kind}}_section_async")
      type(c_ptr),value,intent(in)       :: hostptr
      integer(c_size_t),value,intent(in) :: num_bytes
      logical(c_bool),value,intent(in)   :: condition, if_present
      integer(c_int),value,intent(in)    :: async_arg
    end subroutine
  end interface
  logical :: opt_condition, opt_if_present
  !
  opt_condition = .false.
  opt_if_present = .false.
  if ( present(condition) ) opt_condition = condition
  if ( present(if_present) ) opt_if_present = if_present
  !
  if ( present(num_bytes) ) then
    if ( present(async_arg) ) then
      call gpufortrt_{{update_kind}}_section_async_c_impl(hostptr,&
                                                      num_bytes,&
                                                      logical(opt_condition,c_bool),&
                                                      logical(opt_if_present,c_bool),&
                                                      async_arg)
    else
      call gpufortrt_{{update_kind}}_section_c_impl(hostptr,&
                                                num_bytes,&
                                                logical(opt_condition,c_bool),&
                                                logical(opt_if_present,c_bool),&
                                                gpufortrt_async_noval)
    endif
  else
    if ( present(async_arg) ) then
      call gpufortrt_{{update_kind}}_async_c_impl(hostptr,&
                                              logical(opt_condition,c_bool),&
                                              logical(opt_if_present,c_bool),&
                                              async_arg)
    else
      call gpufortrt_{{update_kind}}_c_impl(hostptr,&
                                        logical(opt_condition,c_bool),&
                                        logical(opt_if_present,c_bool),&
                                        gpufortrt_async_noval)
    endif
  endif
end subroutine
{#######################################################################################}
{% macro render_specialized_update_routines(update_kind,datatypes) %}
{#######################################################################################}
{% for tuple in datatypes %}
subroutine gpufortrt_{{update_kind}}_{{tuple[0]}}_scal(hostptr,condition,if_present,async_arg)
  use iso_c_binding
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  logical,intent(in),optional :: condition, if_present
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg
  !
  call gpufortrt_{{update_kind}}_b(c_loc(hostptr),int({{tuple[1]}},c_size_t),condition,if_present,async_arg)
end subroutine

subroutine gpufortrt_{{update_kind}}_{{tuple[0]}}_arr(hostptr,num_elements,condition,if_present,async_arg)
  use iso_c_binding
  implicit none
  {{tuple[2]}},target,intent(in) :: hostptr
  integer,intent(in) :: num_elements
  logical,intent(in),optional :: condition, if_present
  integer(gpufortrt_handle_kind),intent(in),optional :: async_arg
  !
  call gpufortrt_{{update_kind}}_b(c_loc(hostptr),int({{tuple[1]}},c_size_t),condition,if_present,async_arg)
end subroutine
{% endfor %}{# datatypes #}
{% endmacro %}
{#######################################################################################}
{% macro render_basic_use_device_routines() %}

{% endmacro %}
{#######################################################################################}
