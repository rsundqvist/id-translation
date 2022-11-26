import sqlalchemy

# This value is probably a bit off compared to other real-world scenarios since IDs are very sparse in the IMDb data
MAX_OVERFETCH_FACTOR = 50


class Candidates:
    def __init__(self, engine):

        self.engine = engine
        metadata = sqlalchemy.MetaData()
        metadata.reflect(engine)

        self.id_column = metadata.tables["title_basics"].columns["int_id_tconst"]
        extra_cols = (
            metadata.tables["title_basics"].columns["primaryTitle"],
            metadata.tables["title_basics"].columns["originalTitle"],
            metadata.tables["title_basics"].columns["runtimeMinutes"],
        )
        self.bare_select = sqlalchemy.select(self.id_column, *extra_cols)

    def _exec(self, stmt):
        return list(self.engine.execute(stmt))

    def as_is(self, ids):
        return self._exec(self.bare_select)

    def between(self, ids):
        min_id = min(ids)
        max_id = max(ids)
        select = self.bare_select.where(self.id_column.between(min_id, max_id))
        return self._exec(select)

    def is_in(self, ids):
        return self._exec(self.bare_select.where(self.id_column.in_(ids)))

    def heuristic(self, ids):
        stmt = self.bare_select
        num_ids = len(ids)

        in_clause = stmt.where(self.id_column.in_(ids))
        if num_ids < 1200:
            return self._exec(in_clause)

        min_id = min(ids)
        max_id = max(ids)
        between_clause = stmt.where(self.id_column.between(min_id, max_id))

        if num_ids > 4500:
            return self._exec(between_clause)

        overfetch_factor = (max_id - min_id) / num_ids
        return self._exec(
            in_clause if overfetch_factor > MAX_OVERFETCH_FACTOR else between_clause
        )
