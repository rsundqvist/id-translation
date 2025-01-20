CREATE TABLE uuid_test_table
(
    uuid     uniqueidentifier,
    str_uuid char(36),
    comment  varchar(128)
);

INSERT INTO uuid_test_table (uuid, str_uuid, comment)
VALUES ('3f333df6-90a4-4fda-8dd3-9485d27cee36', '3F333DF6-90a4-4fda-8dd3-9485d27cee36', 'mixed'),
       ('6ecd8c99-4036-403d-bf84-cf8400f67836', '6ecd8c99-4036-403d-bf84-cf8400f67836', 'lower'),
       ('40e6215d-b5c6-4896-987c-f30f3678f608', '40E6215D-B5C6-4896-987C-F30F3678F608', 'upper');

GO
