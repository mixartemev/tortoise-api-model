from datetime import datetime
from passlib.context import CryptContext
from pydantic import BaseModel as BasePyd
from tortoise import Model as BaseModel
from tortoise.contrib.postgres.fields import ArrayField
from tortoise.contrib.pydantic import pydantic_model_creator, PydanticModel, PydanticListModel
from tortoise.contrib.pydantic.creator import PydanticMeta, pydantic_queryset_creator
from tortoise.fields import Field, CharField, IntField, SmallIntField, BigIntField, DecimalField, FloatField,\
    TextField, BooleanField, DatetimeField, DateField, TimeField, JSONField, ForeignKeyRelation, OneToOneRelation, \
    ManyToManyRelation, ForeignKeyNullableRelation, OneToOneNullableRelation, IntEnumField
from tortoise.fields.data import IntEnumFieldInstance, CharEnumFieldInstance
from tortoise.fields.relational import BackwardFKRelation, ForeignKeyFieldInstance, ManyToManyFieldInstance, \
    OneToOneFieldInstance, BackwardOneToOneRelation, RelationalField, ReverseRelation
from tortoise.models import MetaInfo
from tortoise.queryset import QuerySet

from tortoise_api_model import FieldType, PointField, PolygonField, RangeField
from tortoise_api_model.enum import UserStatus, UserRole
from tortoise_api_model.field import DatetimeSecField, SetField

pm_in = PydanticMeta
pm_in.exclude_raw_fields = False
pm_in.max_recursion = 0 # no need to disable backward relations, because recursion=0
pm_out = PydanticMeta
pm_out.max_recursion = 1
pm_out.backward_relations = False


class Model(BaseModel):
    id: int = IntField(pk=True)
    _name: str = 'name'
    _icon: str = '' # https://unpkg.com/@tabler/icons@2.30.0/icons/icon_name.svg
    __pyd: type[PydanticModel] = None
    __pyds: type[PydanticListModel] = None

    @classmethod
    def cols(cls) -> list[dict]:
        meta = cls._meta
        return [{'data': c, 'orderable': c not in meta.fetch_fields or c in meta.fk_fields} for c in meta.fields_map if not c.endswith('_id')]

    @classmethod
    def pyd(cls, inp: bool = False) -> type[PydanticModel]:
        return cls.__pyd or pydantic_model_creator(cls, **{'name': cls.__name__+'-In', 'meta_override': pm_in, 'exclude_readonly': True, 'exclude': ('created_at', 'updated_at')} if inp else {'name': cls.__name__, 'meta_override': pm_out})

    @classmethod
    def pyds(cls) -> type[PydanticListModel]:
        return cls.__pyds or pydantic_queryset_creator(cls)

    @classmethod
    def pageQuery(cls, limit: int = 1000, offset: int = 0, order: [] = None, reps: bool = False) -> QuerySet:
        return cls.all()\
            .order_by(*(order or []))\
            .limit(limit).offset(offset)
            # todo: search and filters

    @classmethod
    async def pagePyd(cls, limit: int = 1000, offset: int = 0) -> PydanticListModel:
        query = cls.all().limit(limit).offset(offset)
        pyd: PydanticModel.__class__ = cls.pyd()
        # total = len(data)+offset if limit-len(data) else await cls.all().count()
        pyds = await cls.pyds().from_queryset(query) # , total=total
        return pyds

    def repr(self):
        if self._name in self._meta.db_fields:
            return getattr(self, self._name)
        return self.__repr__()

    @classmethod
    async def getOrCreateByName(cls, name: str) -> BaseModel:
        if not (obj := await cls.get_or_none(**{cls._name: name})):
            next_id = (await cls.all().order_by('-id').first()).id + 1
            obj = await cls.create(id=next_id, **{cls._name: name})
        return obj


    @classmethod
    async def upsert(cls, data: dict, oid = None):
        meta: MetaInfo = cls._meta

        # pop fields for relations from general data dict
        m2ms = {k: data.pop(k) for k in meta.m2m_fields if k in data}
        bfks = {k: data.pop(k) for k in meta.backward_fk_fields if k in data}
        bo2os = {k: data.pop(k) for k in meta.backward_o2o_fields if k in data}

        # save general model
        # if pk := meta.pk_attr in data.keys():
        #     unq = {pk: data.pop(pk)}
        # else:
        #     unq = {key: data.pop(key) for key, ft in meta.fields_map.items() if ft.unique and key in data.keys()}
        # # unq = meta.unique_together
        # obj, is_created = await cls.update_or_create(data, **unq)
        obj = (await cls.update_or_create(data, **{meta.pk_attr: oid}))[0] if oid else await cls.create(**data)

        # save relations
        for k, ids in m2ms.items():
            m2m_rel: ManyToManyRelation = getattr(obj, k)
            items = [await m2m_rel.remote_model[i] for i in ids]
            await m2m_rel.add(*items)
        for k, ids in bfks.items():
            bfk_rel: ReverseRelation = getattr(obj, k)
            items = [await bfk_rel.remote_model[i] for i in ids]
            [await item.update_from_dict({bfk_rel.relation_field: obj.pk}).save() for item in items]
        for k, oid in bo2os.items():
            bo2o_rel: QuerySet = getattr(obj, k)
            item = await bo2o_rel.model[oid]
            await item.update_from_dict({obj._meta.db_table: obj}).save()

        await obj.fetch_related(*cls._meta.fetch_fields)
        return obj

    @classmethod
    def field_input_map(cls) -> dict:
        def type2input(ft: type[Field]):
            dry = {
                'base_field': hasattr(ft, 'base_field') and {**type2input(ft.base_field)},
                'step': hasattr(ft, 'step') and ft.step,
                'labels': hasattr(ft, 'labels') and ft.labels
            }
            type2inputs: {Field: dict} = {
                CharField: {'input': FieldType.input.name},
                IntField: {'input': FieldType.input.name, 'type': 'number'},
                SmallIntField: {'input': FieldType.input.name, 'type': 'number'},
                BigIntField: {'input': FieldType.input.name, 'type': 'number'},
                DecimalField: {'input': FieldType.input.name, 'type': 'number', 'step': '0.01'},
                FloatField: {'input': FieldType.input.name, 'type': 'number', 'step': '0.001'},
                TextField: {'input': FieldType.textarea.name, 'rows': '2'},
                BooleanField: {'input': FieldType.checkbox.name},
                DatetimeField: {'input': FieldType.input.name, 'type': 'datetime'},
                DatetimeSecField: {'input': FieldType.input.name, 'type': 'datetime'},
                DateField: {'input': FieldType.input.name, 'type': 'date'},
                TimeField: {'input': FieldType.input.name, 'type': 'time'},
                JSONField: {'input': FieldType.input.name},
                IntEnumFieldInstance: {'input': FieldType.select.name},
                CharEnumFieldInstance: {'input': FieldType.select.name},
                ForeignKeyFieldInstance: {'input': FieldType.select.name},
                OneToOneFieldInstance: {'input': FieldType.select.name},
                ManyToManyFieldInstance: {'input': FieldType.select.name, 'multiple': True},
                ForeignKeyRelation: {'input': FieldType.select.name, 'multiple': True},
                OneToOneRelation: {'input': FieldType.select.name},
                BackwardOneToOneRelation: {'input': FieldType.select.name},
                ManyToManyRelation: {'input': FieldType.select.name, 'multiple': True},
                ForeignKeyNullableRelation: {'input': FieldType.select.name, 'multiple': True},
                BackwardFKRelation: {'input': FieldType.select.name, 'multiple': True},
                ArrayField: {'input': FieldType.select.name, 'multiple': True},
                SetField: {'input': FieldType.select.name, 'multiple': True},
                OneToOneNullableRelation: {'input': FieldType.select.name},
                PointField: {'input': FieldType.collection.name, **dry},
                PolygonField: {'input': FieldType.list.name, **dry},
                RangeField: {'input': FieldType.collection.name, **dry},
            }
            return type2inputs[ft]

        def field2input(key: str, field: Field):
            attrs: dict = {'required': not field.null}
            if isinstance(field, CharEnumFieldInstance):
                attrs.update({'options': {en.name: en.value for en in field.enum_type}})
            elif isinstance(field, IntEnumFieldInstance) or isinstance(field, SetField):
                attrs.update({'options': {en.value: en.name.replace('_', ' ') for en in field.enum_type}})
            elif isinstance(field, RelationalField):
                attrs.update({'source_field': field.source_field})  # 'table': attrs[key]['multiple'],
            elif field.generated or ('auto_now' in field.__dict__ and (field.auto_now or field.auto_now_add)): # noqa
                attrs.update({'auto': True})
            return {**type2input(type(field)), **attrs}

        return {key: field2input(key, field) for key, field in cls._meta.fields_map.items() if not key.endswith('_id')}

    class Meta:
        abstract = True


class TsModel(Model):
    created_at: datetime|None = DatetimeSecField(auto_now_add=True)
    updated_at: datetime|None = DatetimeSecField(auto_now=True)

    class Meta:
        abstract = True


class User(TsModel):
    id: int = SmallIntField(True)
    status: UserStatus = IntEnumField(UserStatus, default=UserStatus.Wait)
    username: str = CharField(95, unique=True)
    email: str|None = CharField(100, unique=True, null=True)
    password: str|None = CharField(60, null=True)
    phone: int|None = BigIntField(null=True)
    role: UserRole = IntEnumField(UserRole, default=UserRole.Client)

    _icon = 'user'
    _name = 'username'

    def vrf_pwd(self, pwd: str) -> bool:
        return CryptContext(schemes=["bcrypt"]).verify(pwd, self.password)

    class Meta:
        table_description = "Users"

class UserPwd(BasePyd):
    password: str

class UserReg(UserPwd):
    username: str
    email: str|None = None
    phone: int|None = None

class UserUpdate(BasePyd):
    username: str
    status: UserStatus
    email: str|None
    phone: int|None
    role: UserRole

class UserSchema(UserUpdate):
    id: int
