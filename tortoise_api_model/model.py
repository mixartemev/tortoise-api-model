from datetime import datetime

from passlib.context import CryptContext
from pydantic import ConfigDict
from tortoise import Model as BaseModel
from tortoise.fields import Field, CharField, IntField, SmallIntField, BigIntField, DecimalField, FloatField,\
    TextField, BooleanField, DatetimeField, DateField, TimeField, JSONField, ForeignKeyRelation, OneToOneRelation, \
    ManyToManyRelation, ForeignKeyNullableRelation, OneToOneNullableRelation, IntEnumField
from tortoise.fields.data import IntEnumFieldInstance, CharEnumFieldInstance
from tortoise.fields.relational import BackwardFKRelation, ForeignKeyFieldInstance, ManyToManyFieldInstance, \
    OneToOneFieldInstance, BackwardOneToOneRelation, RelationalField, ReverseRelation
from tortoise.models import MetaInfo
from tortoise.queryset import QuerySet
from tortoise.signals import pre_save

from tortoise_api_model import FieldType, PointField, PolygonField, RangeField
from tortoise_api_model.enums import UserStatus, UserRole
from tortoise_api_model.fields import DatetimeSecField, SetField


class Model(BaseModel):
    id: int = IntField(pk=True)
    _name: str = 'name'
    _icon: str  # https://unpkg.com/@tabler/icons@2.30.0/icons/icon_name.svg
    _order: int = 1
    _hidden: bool = False
    _options: {str: {int: str}}
    # _parent_model: str = None # todo: for dropdowns

    async def repr(self):
        if self._name in self._meta.db_fields:
            return getattr(self, self._name)
        return self.__repr__()

    @classmethod
    async def load_rel_options(cls):
        res = {}
        for fk in cls._meta.fetch_fields:
            field: RelationalField = cls._meta.fields_map[fk]
            first: {str: str} = {'': 'Empty'} if field.null else {}
            res[fk] = {**first, **{x.pk: await x.repr() for x in await field.related_model.all()}}
        cls._options = res

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
                # ArrayField: {'input': FieldType.select.name, 'multiple': True},
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
                attrs.update({'options': cls._options[key], 'source_field': field.source_field})  # 'table': attrs[key]['multiple'],
            elif field.generated or ('auto_now' in field.__dict__ and (field.auto_now or field.auto_now_add)): # noqa
                attrs.update({'auto': True})
            return {**type2input(type(field)), **attrs}

        return {key: field2input(key, field) for key, field in cls._meta.fields_map.items() if not key.endswith('_id')}

    async def with_rels(self) -> dict:
        async def check(field: Field, key: str):
            prop = getattr(self, key)

            # if isinstance(prop, date):
            #     return prop.__str__().split('+')[0].split('.')[0] # '+' separates tz part, '.' separates millisecond part
            # if isinstance(prop, Polygon):
            #     return prop.points
            # if isinstance(prop, Range):
            #     return prop.lower, prop.upper
            if isinstance(field, RelationalField):
                if isinstance(prop, Model):
                    return await prop._rel_pack()
                elif isinstance(prop, ReverseRelation) and isinstance(prop.related_objects, list):
                    return [await d._rel_pack() for d in prop.related_objects]
                elif prop is None:
                    return ''
                return None
            return getattr(self, key)

        return {key: await check(field, key) for key, field in self._meta.fields_map.items() if not key.endswith('_id')}

    async def _rel_pack(self) -> dict:
        return {'id': self.id, 'type': self.__class__.__name__, 'repr': await self.repr()}

    class Meta:
        abstract = True


class TsModel(Model):
    created_at: datetime = DatetimeSecField(auto_now_add=True)
    updated_at: datetime = DatetimeSecField(auto_now=True)

    class Meta:
        abstract = True


class User(TsModel):
    id: int = SmallIntField(True)
    status: UserStatus = IntEnumField(UserStatus, default=UserStatus.Wait)
    username: str = CharField(95, unique=True)
    email: str|None = CharField(100, unique=True, null=True)
    password: str = CharField(60)
    phone: int|None = BigIntField(null=True)
    role: UserRole = IntEnumField(UserRole, default=UserRole.Client)

    _icon = 'user'
    _name = 'username'
    _cc = CryptContext(schemes=["bcrypt"])

    def vrf_pwd(self, pwd: str) -> bool:
        return self._cc.verify(pwd, self.password)

    class Meta:
        table_description = "Users"
    #
    # class PydanticMeta:
    #     model_config = ConfigDict(extra='allow')


@pre_save(User)
async def hash_pwd(_, user: User, __, ___) -> None:
    user.password = User._cc.hash(user.password)
