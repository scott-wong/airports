-- 平台侧一次性操作：把 airports schema 加进 PostgREST 暴露列表。
-- 需要超级用户（postgres）。当前 project_admin 既非超级用户也不继承任何角色，执行会失败。
-- 顺序很关键：先跑 airports-collector migrate 建好 schema，再执行本文件；
-- 若把尚未存在的 schema 写进 pgrst.db_schemas，PostgREST 重启会报错。

ALTER ROLE postgres SET pgrst.db_schemas = 'public, flight_ops, airports';
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';

-- 校验：
--   SELECT current_setting('pgrst.db_schemas', true);
-- 期望输出 public, flight_ops, airports
