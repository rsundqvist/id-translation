{%- set _parts = fullname.split('.') -%}
{%- if _parts | length > 2 -%}
{%- set _title = _parts[-2:] | join('.') -%}
{%- else -%}
{%- set _title = fullname -%}
{%- endif %}
{{ _title | escape | underline}}

.. currentmodule:: {{ module }}

.. auto{{ objtype }}:: {{ objname }}
