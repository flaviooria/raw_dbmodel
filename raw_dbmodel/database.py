from logging import getLogger
from typing import List

from sqlalchemy import Engine
from sqlmodel import SQLModel, create_engine
from typing_extensions import Type

from raw_dbmodel.logger import setup_logging
from raw_dbmodel.settings import config

setup_logging()
logger = getLogger(__name__)

engine: Engine = create_engine(config.uri, echo=False)


def create_tables(models: List[Type]):
    tables: list[Type[SQLModel]] = []
    for _cls in models:
        if isinstance(_cls, type):
            try:
                if issubclass(_cls, SQLModel) and _cls is not SQLModel and hasattr(_cls, '__table__'):
                    tables.append(_cls)
                else:
                    logger.warning(f'{_cls.__name__} class is not a table')
            except TypeError as te:
                logger.error(te)
                raise

    if len(tables) > 0:
        print_tables = [f'{cls.__name__} class has been added as table name: [b blue]{cls.__tablename__}[/b blue]' for
                        cls in tables]
        for msg in print_tables:
            logger.info(msg)

        SQLModel.metadata.create_all(bind=engine, tables=[cls.__table__ for cls in tables if hasattr(cls, '__table__')])
    else:
        logger.error('Could not create the tables, check that the imported classes are correct.')


__all__ = ["engine", "create_tables"]


def __dir__() -> list[str]:
    return sorted(list(__all__))
