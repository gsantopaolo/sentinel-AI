import logging
from sqlalchemy.orm import Session
from src.lib_py.models.models import Source
from typing import List, Optional

logger = logging.getLogger(__name__)

class SourceLogic:
    def __init__(self, db_session: Session):
        self.db_session = db_session
        logger.info("✅ SourceLogic initialized with a database session.")

    def create_source(self, name: str, type: str, config: Optional[dict] = None) -> Source:
        logger.info(f"🗄️ Attempting to create source: {name} (Type: {type})")
        try:
            new_source = Source(name=name, type=type, config=config)
            self.db_session.add(new_source)
            self.db_session.commit()
            self.db_session.refresh(new_source)
            logger.info(f"✅ Source created successfully with ID: {new_source.id}")
            return new_source
        except Exception as e:
            self.db_session.rollback()
            logger.error(f"❌ Error creating source {name}: {e}")
            raise

    def get_source(self, source_id: int) -> Optional[Source]:
        logger.info(f"🗄️ Attempting to retrieve source with ID: {source_id}")
        source = self.db_session.query(Source).filter(Source.id == source_id).first()
        if source:
            logger.info(f"✅ Source with ID {source_id} found: {source.name}")
        else:
            logger.warning(f"⚠️ Source with ID {source_id} not found.")
        return source

    def get_all_sources(self) -> List[Source]:
        logger.info("🗄️ Attempting to retrieve all sources.")
        sources = self.db_session.query(Source).all()
        logger.info(f"✅ Retrieved {len(sources)} sources.")
        return sources

    def update_source(self, source_id: int, name: Optional[str] = None, type: Optional[str] = None, config: Optional[dict] = None, is_active: Optional[bool] = None) -> Optional[Source]:
        logger.info(f"🗄️ Attempting to update source with ID: {source_id}")
        source = self.get_source(source_id)
        if source:
            if name is not None: 
                source.name = name
            if type is not None:
                source.type = type
            if config is not None:
                source.config = config
            if is_active is not None:
                source.is_active = is_active
            try:
                self.db_session.commit()
                self.db_session.refresh(source)
                logger.info(f"✅ Source with ID {source_id} updated successfully.")
                return source
            except Exception as e:
                self.db_session.rollback()
                logger.error(f"❌ Error updating source {source_id}: {e}")
                raise
        else:
            logger.warning(f"⚠️ Source with ID {source_id} not found for update.")
        return None

    def delete_source(self, source_id: int) -> bool:
        logger.info(f"🗄️ Attempting to delete source with ID: {source_id}")
        source = self.get_source(source_id)
        if source:
            try:
                self.db_session.delete(source)
                self.db_session.commit()
                logger.info(f"✅ Source with ID {source_id} deleted successfully.")
                return True
            except Exception as e:
                self.db_session.rollback()
                logger.error(f"❌ Error deleting source {source_id}: {e}")
                raise
        else:
            logger.warning(f"⚠️ Source with ID {source_id} not found for deletion.")
        return False
