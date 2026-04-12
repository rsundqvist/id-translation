from sqlalchemy import URL, create_engine

_url = URL.create(
    drivername="postgresql",
    host="localhost",
    username="postgres",
)
ENGINE = create_engine(_url)
