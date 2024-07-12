from datetime import datetime
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Type, Union

import pandas as pd
import sqlalchemy.sql
from pandas import DataFrame
from sqlalchemy import Connection, CursorResult, text
from sqlmodel import inspect, SQLModel
from typing_extensions import Generic

from raw_dbmodel._abstracts import RepositoryAbstract
from raw_dbmodel._types import _T, DictOrStr, ListStrOrNone, TypeMode
from raw_dbmodel.database import engine as engine
from raw_dbmodel.exceptions import (DictOrStrType, ListStrOrNoneType,
                                    ModeOperatorError, ParameterTypeError)
from raw_dbmodel.utils import is_dict_or_str, is_list_str_or_none


class DotDict(dict):
    """
    class to map the data in dictionary and access it through the dot
    """

    def __getattr__(self, key):

        try:
            return self[key]
        except KeyError:
            raise AttributeError(f"'Object has no attribute '{key}'")

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError:
            raise AttributeError(f"'Object has no attribute '{key}'")


class RepositoryBase(Generic[_T], RepositoryAbstract):

    def __init__(self) -> None:

        try:
            if engine is None:
                raise Exception('Engine not could None')

            self.__engine = engine
        except Exception:
            raise

        self.__model: Optional[Type[_T]] = None
        self.__fields = "*"
        self.__query = ""

    @staticmethod
    def transaction(func: Callable[..., Union[DataFrame, CursorResult[Any]]]):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            with engine.begin() as connection:
                return func(self, connection, *args, **kwargs)

        return wrapper

    @classmethod
    def __get_value_formated(cls, value: str, separator: str):
        new_value = ''
        if isinstance(value, str):
            new_value = f"'{value}'{separator}"
        if isinstance(value, int):
            new_value = f"{value}{separator}"
        if isinstance(value, float):
            new_value = f"{value}{separator}"
        if isinstance(value, bool):
            new_value = f"{value}{separator}"
        if isinstance(value, datetime):
            new_value = f"'{value.isoformat()}'{separator}"
        if value is None:
            new_value = f"{sqlalchemy.sql.null()}{separator}"

        return new_value

    @classmethod
    def __get_where_conditions(cls, where: DictOrStr,
                               operators: ListStrOrNone = None):

        if not is_dict_or_str(where):
            raise ParameterTypeError(DictOrStrType)

        if not is_list_str_or_none(operators):
            raise ParameterTypeError(ListStrOrNoneType)

        if isinstance(where, str):
            return where

        if isinstance(where, dict):
            _where = ''

            for index, (field, value) in enumerate(where.items()):
                separator = ' and '
                _where += f"{field} = "

                if operators is not None:
                    if index < len(operators):
                        separator = f' {operators[index]} '

                if index == len(where.values()) - 1:
                    separator = ' '

                _where += cls.__get_value_formated(value, separator)
            return _where

    @property
    def model(self) -> Type[_T]:

        if self.__model is None:
            raise NotImplementedError(
                "You should implement the model property in the subclass")

        return self.__model

    @model.setter
    def model(self, value: Type[_T]):
        self.__model = value

    @transaction
    def __execute(self, connection: Optional[Connection], /, statement: Union[str, Type[_T]],
                  parameters: Optional[Union[List[Type[_T]], Dict[str, Any]]] = None, *,
                  mode: TypeMode = 'sql') -> \
            DataFrame | CursorResult[Any]:
        try:

            if mode != 'sql' and mode != 'as_pd':
                raise ModeOperatorError(
                    'Mode not is \'sql\' or \'as_pd\'')

            if mode == 'as_pd':
                return pd.read_sql_query(text(statement), connection)

            if parameters is not None:
                return connection.execute(statement, parameters)

            return connection.execute(text(statement))

        except Exception:
            raise

    def fields(self, fields: str) -> 'RepositoryBase[_T]':
        """
            Sets the fields to be selected in the SQL query.

            Parameters
            ----------
            fields : str
                A string containing the field names to be selected, separated by commas.

            Returns
            -------
            RepositoryBase[_T]
                The current repository instance with the specified fields set.

            Examples
            --------
            Setting the fields to select in the query:

            >>> repository = RepositoryBase()
            >>> repository.fields('id, name, age')
            RepositoryBase[Model]

            This will result in the following query being constructed when `get_data` is called:

            >>> repository.get_data()
            # SQL query constructed: "select id, name, age from tablename"
        """
        self.__fields = fields

        return self

    def insert(self, model: Type[_T], *, have_autoincrement_default: bool = True) -> _T:
        """
        Insert a new model into the database.

        Parameters
        ----------
            model: Type[_T]
                The model to be inserted into the database.
            have_autoincrement_default: bool
                A flag to specify whether to include autoincrement fields in the insert query.

        Returns
        -------
            _T
                The inserted model.

        Examples
        --------
        >>> repository = RepositoryBase()
        >>> class User(SQLModel):
        >>>     name: str
        >>>     age: int
        >>>     id: int

        >>> repository.model = User
        >>> user = User(id=1, name="Jhon", age=25)
        >>> repository.insert(user)
        User(id=1, name="Jhon", age=25)

        If the flag `have_autoincrement_default` is set ``False``, It's because the ID or primary key
        is generated for database automatic

        >>> user = User(name="Lauri", age=25)
        >>> repository.insert(user, have_autoincrement_default=False)
        User(id=2, name="Lauri", age=25)

        Raises:
            Any specific exceptions that might be raised during the insert operation.

        """
        model_dict: dict = model.model_dump()

        if have_autoincrement_default:
            table = inspect(self.model).tables[0]
            columns_pks = [column.name for column in table.primary_key.columns]

            for field_pk in columns_pks:
                for key in model_dict.keys():
                    if field_pk == key:
                        model_dict.pop(field_pk)

        _columns = ', '.join(model_dict.keys())
        _values = ''
        field_values = model_dict.values()

        for index, value in enumerate(field_values):
            separator = ', '

            if index == len(field_values) - 1:
                separator = ' '

            _values += self.__get_value_formated(value, separator)

        _sql = f"insert into {model.__tablename__} ({_columns}) values ({_values});"

        try:
            self.__execute(_sql)
            return model
        except ModeOperatorError:
            raise
        except Exception:
            raise

    def insert_all(self, *, models: List[Type[_T]], have_autoincrement_default: bool = True) -> bool:
        """
        Insert a list of models into the database.

        Parameters
        ----------
            models: list[Type[_T]]
                The list of models to be inserted into the database.
            have_autoincrement_default: bool
                A flag to specify whether to include autoincrement fields in the insert query.

        Returns
        -------
            bool
                The inserted model.

        Examples
        --------
        >>> repository = RepositoryBase()
        >>> class User(SQLModel):
        >>>     name: str
        >>>     age: int
        >>>     id: int

        >>> repository.model = User
        >>> user = User(id=1, name="Jhon", age=25)
        >>> user2 = User(id=2, name="Jhon2", age=25)
        >>> user_list = [user, user2]
        >>> repository.insert_all(user_list)
        True

        If the flag `have_autoincrement_default` is set ``False``, It's because the ID or primary key
        is generated for database automatic

        >>> user = User(id=1, name="Jhon", age=25)
        >>> user2 = User(id=2, name="Jhon2", age=25)
        >>> user_list = [user, user2]
        >>> repository.insert_all(user_list, have_autoincrement_default=False)
        True

        Raises:
            Any specific exceptions that might be raised during the insert operation.

        """
        try:

            models = [{**data.model_dump()} for data in models]
            _sql = self.model.__table__.insert()

            if have_autoincrement_default:
                table = inspect(self.model).tables[0]
                columns_pks = [
                    column.name for column in table.primary_key.columns]

                for field_pk in columns_pks:
                    for model in models:
                        if field_pk in model.keys():
                            model.pop(field_pk)
                            continue

                _columns = ', '.join(models[0].keys())
                _values = ', '.join(f":{key}" for key in models[0].keys())

                _sql = f"insert into {self.model.__tablename__} ({_columns}) values ({_values})"

            result = self.__execute(_sql, models)

            return bool(result.rowcount)
        except Exception:
            raise

    def get_data(self) -> 'RepositoryBase[_T]':
        """
        Constructs an SQL query to select fields from a table and stores it in the `__query` attribute.

        The query is built using the table name defined in the model and the specified fields.
        The method returns the current repository instance.

        Returns
        -------
        RepositoryBase[_T]
            The current repository instance with the constructed SQL query stored in `__query`.
        """

        self.__query = f"select {self.__fields} from {self.model.__tablename__}"

        return self

    def get_all(self, model: Optional[Type[_T]] = None) -> Optional[List[_T]]:
        """
        Retrieves all records from the table corresponding to the given model and returns them as a list of model
        instances.

        If a model is provided, it updates the `self.model` attribute with the provided model.
        If `self.model` is not set, an exception is raised.
        Executes a SQL query to fetch all records from the table and converts the results into instances of the model.

        Parameters
        ----------
        model : Optional[Type[_T]], optional
            The model class to be used for fetching records. If not provided, the existing `self.model` is used.

        Returns ------- Optional[List[_T]] A list of instances of the model populated with data from the table.
        Returns an empty list if no records are found.

        Example
        -------
        >>> userRepository = RepositoryBase()
        >>> userRepository.get_all()
        [User(id=1, name="Jhon", age=25), User(id=2, name="Gabe", age=25), ...]

        Raises
        ------
        Exception
            If `self.model` is not set.
        """
        if model is not None:
            self.model = model

        if self.model is None:
            raise Exception('Property model not implemented')

        _sql = f"select * from {self.model.__tablename__}"

        generic_models: List[Type[_T]] = []
        models_from_db = self.__execute(_sql, mode='as_pd')

        list_model = models_from_db.to_dict('records')

        for model in list_model:
            inherited_model = self.model(**model)
            generic_models.append(inherited_model)

        return generic_models

    def get_one(self, where: DictOrStr,
                operators: ListStrOrNone = None) -> 'RepositoryBase[_T]':
        """
        Constructs an SQL query to select a single record from the table based on the specified conditions and stores
        it in the ``__query`` attribute.

           Validates the types of ``where`` and ``operators`` parameters. If the ``self.model`` is not set,
           it raises an exception. Constructs the SQL `WHERE` clause from the provided conditions and operators.

           Parameters
           ----------
           where : DictOrStr
               The conditions to be used in the SQL ``WHERE`` clause. Can be a dictionary or a string.
           operators : ListStrOrNone, optional
               A list of SQL operators to be used in the ``WHERE`` clause. If not provided, defaults to ``None``.

           Returns
           -------
           RepositoryBase[_T]
               The current repository instance with the constructed SQL query stored in ``__query``.

            Examples
            --------
            >>> repository = RepositoryBase()

            * Using as_model method

            >>> repository.get_one({"name": "Jhon"}).as_model()
            User(id=1, name='Jhon', age=25)

            * Using as_dict method

            >>> repository.get_one({"name": "Jhon"}).as_dict()
            {"id": 1, "name": 'Jhon', "age": 25}

            * Using as_df method
            >>> repository.get_one("name = 'Jhon'").as_df()
               id      name     age
            0   1  John Doe     25


           Raises
           ------
           ParameterTypeError
               If the type of ``where`` is not ``DictOrStr`` or if the type of ``operators`` is not ``ListStrOrNone``.
           NotImplementedError
               If ``self.model`` is not set.
       """
        if not is_dict_or_str(where):
            raise ParameterTypeError(DictOrStrType)

        if not is_list_str_or_none(operators):
            raise ParameterTypeError(ListStrOrNoneType)

        if self.model is None:
            raise NotImplementedError('Property model not implemented')

        _where = self.__get_where_conditions(where, operators)

        _sql = f"select {self.__fields} from {self.model.__tablename__} where {_where};"

        self.__query = _sql

        return self

    def update(self, set_fields: DictOrStr, where: DictOrStr,
               operators: ListStrOrNone = None) -> bool:
        """
            Constructs and executes an SQL update query to
            update records in the table based on the specified conditions.

            Validates the types of ``set_fields``, ``where``, and ``operators`` parameters.
            If the ``self.model`` is not set, it raises an exception.
            Constructs the SQL `SET` and `WHERE` clauses from the provided parameters.

            Parameters
            ----------
            set_fields : DictOrStr
                The fields and their new values to be set in the update query. Can be a dictionary or a string.
            where : DictOrStr
                The conditions to be used in the SQL `WHERE` clause. Can be a dictionary or a string.
            operators : ListStrOrNone, optional
                A list of SQL operators to be used in the `WHERE` clause. If not provided, defaults to `None`.

            Returns
            -------
            bool
                ``True`` if the update query affected any rows, ``False`` otherwise.

            Raises
            ------
            ParameterTypeError
                If the type of `set_fields`, `where`, or `operators` is not as expected.
            NotImplementedError
                If `self.model` is not set.

            Examples
            --------
            Updating a record with specified fields and conditions:

            >>> repository = RepositoryBase()
            >>> class User(SQLModel):
            >>>     name: str
            >>>     age: int
            >>>     id: int

            >>> repository.model = User
            >>> repository.update({'name': 'John Doe', 'age': 30}, {'id': 1})
            True

            This will result in the following query being executed:

            >>> repository.update('name = \'Jhon Doe\', age = 30', 'id = 1')
            # SQL query executed: "update user_model set name = 'John Doe', age = 30 where id = 1;"

            >>> repository.update('name = \'Jhon Doe\', age = 30', 'id = 1, age > 20', ['and'])
            # SQL query executed: "update user_model set name = 'John Doe', age = 30 where id = 1 and age > 20;"
        """
        if not is_dict_or_str(set_fields):
            raise ParameterTypeError(DictOrStrType)

        if not is_dict_or_str(where):
            raise ParameterTypeError(DictOrStrType)

        if not is_list_str_or_none(operators):
            raise ParameterTypeError(ListStrOrNoneType)

        _set = ''
        _where = ''

        if self.model is None:
            raise NotImplementedError('Property model not implemented')

        if isinstance(set_fields, str):
            _set = set_fields

        if isinstance(set_fields, dict):
            for index, (field, value) in enumerate(set_fields.items()):
                _set += f"{field} = "
                separator = ', '

                if index == (len(set_fields.values()) - 1):
                    separator = ' '

                _set += self.__get_value_formated(value, separator)

        _where = self.__get_where_conditions(where, operators)

        _sql = f"update {self.model.__tablename__} set {_set} where {_where};"

        result = self.__execute(_sql)

        return bool(result.rowcount)

    def delete(self, where: DictOrStr, operators: ListStrOrNone = None) -> bool:
        """
            Constructs and executes an SQL delete query to remove records
            from the table based on the specified conditions.

            Validates the types of `where` and `operators` parameters. If the `self.model` is not set,
            it raises an exception. Constructs the SQL `WHERE` clause from the provided conditions and operators.

            Parameters
            ----------
            where : DictOrStr
                The conditions to be used in the SQL `WHERE` clause. Can be a dictionary or a string.
            operators : ListStrOrNone, optional
                A list of SQL operators to be used in the `WHERE` clause. If not provided, defaults to `None`.

            Returns
            -------
            bool
                `True` if the delete query affected any rows, `False` otherwise.

            Raises
            ------
            ParameterTypeError
                If the type of `where` or `operators` is not as expected.
            NotImplementedError
                If `self.model` is not set.

            Examples
            --------
            Deleting records with specified conditions:

            >>> repository = RepositoryBase()
            >>> class User(SQLModel):
            >>>     name: str
            >>>     age: int
            >>>     id: int

            >>> repository.model = User
            >>> repository.delete({'id': 1})
            True

            This will result in the following query being executed:

            >>> repository.delete('id = 1')
            # SQL query executed: "delete from user_model where id = 1;"
        """
        if not is_dict_or_str(where):
            raise ParameterTypeError(DictOrStrType)

        if not is_list_str_or_none(operators):
            raise ParameterTypeError(ListStrOrNoneType)

        _where = ''

        _where = self.__get_where_conditions(where, operators)

        _sql = f"delete from {self.model.__tablename__} where {_where}"

        result = self.__execute(_sql)

        return bool(result.rowcount)

    def as_model(self) -> Optional[_T]:
        """
            Executes the stored SQL query and returns the result as an instance of the model.

            If the query results in an empty set, `None` is returned. The method also attempts to parse any datetime fields
            from the result.

            Returns
            -------
            Optional[_T]
                An instance of the model populated with the query result, or `None` if no result is found.

            Examples
            --------
            Retrieving a single record as a model instance:

            >>> repository = RepositoryBase()
            >>> repository.fields('id, name, created_at').get_data()
            >>> model_instance = repository.as_model()
            >>> model_instance
            UserModel(id=1, name='John Doe', created_at=datetime.datetime(2023, 1, 1, 0, 0))
        """
        if self.__query != "":
            model_found = self.__execute(self.__query, mode='as_pd')

            if model_found.empty:
                return None

            model = model_found.to_dict('records')[0]

            for key in model.keys():
                try:
                    _datetime = datetime.fromisoformat(model[key])
                    if isinstance(_datetime, datetime):
                        model[key] = _datetime
                except Exception:
                    continue

            return self.model(**model)
        return None

    def as_dict(self) -> Optional[DotDict]:
        """
           Executes the stored SQL query and returns the result as a dictionary.

           If the query results in an empty set, `None` is returned.

           Returns
           -------
           Optional[DotDict]
               A dictionary representation of the query result, or `None` if no result is found.

           Examples
           --------
           Retrieving a single record as a dictionary:

           >>> repository = RepositoryBase()
           >>> repository.fields('id, name, created_at').get_data()
           >>> result_dict = repository.as_dict()
           >>> result_dict
           DotDict({'id': 1, 'name': 'John Doe', 'created_at': '2023-01-01T00:00:00'})
       """
        if self.__query != "":
            model_found = self.__execute(self.__query, mode='as_pd')

            if model_found.empty:
                return None

            model = model_found.to_dict('records')[0]

            return DotDict(model)
        return None

    def as_df(self) -> Optional[DataFrame]:
        """
           Executes the stored SQL query and returns the result as a pandas DataFrame.

           If the query results in an empty set, `None` is returned.

           Returns
           -------
           Optional[DataFrame]
               A pandas DataFrame containing the query result, or `None` if no result is found.

           Examples
           --------
           Retrieving query results as a DataFrame:

           >>> repository = RepositoryBase()
           >>> repository.fields('id, name, created_at').get_data()
           >>> result_df = repository.as_df()
           >>> result_df
              id      name          created_at
           0   1  John Doe  2023-01-01 00:00:00
       """
        if self.__query != "":
            model_found = self.__execute(self.__query, mode='as_pd')

            if model_found.empty:
                return None

            return model_found

        return None
