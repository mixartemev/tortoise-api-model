from dataclasses import make_dataclass, field, fields
from datetime import datetime
from typing import Self

from pydantic import ConfigDict
from tortoise import Model as TortModel
from tortoise.fields import Now
from tortoise.signals import Signals

from x_model.field import DatetimeSecField, IntField
from x_model.types import BaseUpd


class TsTrait:
    created_at: datetime | None = DatetimeSecField(auto_now_add=True, db_default=Now())
    updated_at: datetime | None = DatetimeSecField(auto_now=True, db_default=Now())


class Model(TortModel):
    id: int = IntField(True)

    _in_type: type[BaseUpd] = None  # overridable
    _name: tuple[str] = ("name",)
    _sorts: tuple[str] = ("-id",)

    def __repr__(self, sep: str = " ") -> str:
        return sep.join(str(getattr(self, name_fragment)) for name_fragment in self._name)

    # @classmethod
    # def out_type(cls) -> type[BaseModel]:
    #     if not cls._out_type:
    #         cls._out_type = pydantic_model_creator(cls, name=cls.__name__ + "Out")
    #     return cls._out_type

    @classmethod
    def in_type(cls, with_pk: bool = False) -> type[BaseUpd]:
        if not getattr(cls, cn := "Upd" if with_pk else "New", None):
            fields: list[tuple[str, type] | tuple[str, type, field]] = []
            meta = cls._meta
            for fn in meta.db_fields:
                if (f := meta.fields_map[fn]).pk and not with_pk:
                    continue
                if getattr(f, "auto_now", None) or getattr(f, "auto_now_add", None):
                    continue
                fld = fn, getattr(f, "enum_type", f.field_type)
                if f.default or f.null or (f.allows_generated and not f.pk) or not f.required:
                    fld += (field(default_factory=dict) if f.default == {} else field(default=f.default),)
                fields.append(fld)
            # for fn in meta.fk_fields:
            #     f = meta.fields_map[fn]
            #     fld = fn+"_id", int
            #     if f.default or f.allows_generated or f.null or not f.required:
            #         fld += (field(default=f.default),)
            #     fields.append(fld)
            pre_saves = {f.__name__ for f in cls._listeners[Signals.pre_save].get(cls, [])}
            dcl = make_dataclass(cls.__name__ + cn, fields, bases=(BaseUpd,), kw_only=True)
            dcl._unq = meta.o2o_fields - pre_saves
            dcl._unq |= set((meta.unique_together or ((),))[0])
            dcl._unq |= {
                k
                for k, f in meta.fields_map.items()
                if f.unique and k not in meta.backward_fk_fields | meta.backward_o2o_fields | meta.m2m_fields
            }
            if not with_pk:
                dcl._unq -= {"id"}
            dcl._unq = {meta.fields_map[f].source_field or f for f in dcl._unq}
            setattr(cls, cn, dcl)

        return getattr(cls, cn)

    # # # CRUD Methods # # #
    @classmethod
    def validate(cls, dct: dict, with_pk: bool = None) -> BaseUpd:
        dcl = cls.in_type("id" in dct if with_pk is None else with_pk)
        field_names = [n.name for n in fields(dcl)]
        return dcl(**{k: v for k, v in dct.items() if k in field_names})

    @classmethod
    async def get_or_create_by_name(cls, name: str, attr_name: str = None, def_dict: dict = None) -> Self:
        attr_name = attr_name or list(cls._name)[0]
        if not (obj := await cls.get_or_none(**{attr_name: name})):
            next_id = (await cls.all().order_by("-id").first()).id + 1
            obj = await cls.create(id=next_id, **{attr_name: name}, **(def_dict or {}))
        return obj

    class PydanticMeta:
        model_config = ConfigDict(use_enum_values=True)
        # include: tuple[str, ...] = ()
        # exclude: tuple[str, ...] = ("Meta",)
        # computed: tuple[str, ...] = ()
        backward_relations: bool = False  # True
        max_recursion: int = 1  # default: 3
        # allow_cycles: bool = False
        # exclude_raw_fields: bool = False  # True
        # sort_alphabetically: bool = False
        # model_config: ConfigDict | None = None

    class Meta:
        abstract = True
