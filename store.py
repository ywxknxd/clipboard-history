"""数据层：所有的 SQL 都集中在这个文件，别的模块不许直接碰数据库。

为什么不用 ORM：数据只有两张表，写 SQL 比引入依赖更直白，你也更容易看懂改懂。
"""

import hashlib
import os
import sqlite3
import time

import paths

# 单条内容超过这个长度就不记了。剪贴板里偶尔会进来整篇文档或一坨 base64，
# 存下来只会让库变大、列表变慢，实际也用不上。
MAX_LEN = 100_000

DB_PATH = os.path.join(paths.app_dir(), "data.db")

_conn = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS history (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  content    TEXT    NOT NULL,
  hash       TEXT    NOT NULL UNIQUE,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hist_updated ON history(updated_at DESC);

CREATE TABLE IF NOT EXISTS phrases (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  content    TEXT    NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
"""


def _migrate_phrases(cx):
    """把老版带「标题」的常用语表换成只有内容的表。

    标题已经不需要了（用户明确要求只留内容），但旧库不能直接删，
    所以把原内容搬过去、标题丢弃。已经迁移过的库这段直接跳过。
    """
    cols = [r[1] for r in cx.execute("PRAGMA table_info(phrases)")]
    if "title" not in cols:
        return 0

    old = cx.execute("SELECT content, created_at, updated_at FROM phrases").fetchall()
    cx.execute("ALTER TABLE phrases RENAME TO phrases_old")
    cx.execute("""
        CREATE TABLE phrases (
          id         INTEGER PRIMARY KEY AUTOINCREMENT,
          content    TEXT    NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
    """)
    for row in old:
        cx.execute(
            "INSERT INTO phrases (content, created_at, updated_at) VALUES (?, ?, ?)",
            (row[0], row[1], row[2]),
        )
    cx.execute("DROP TABLE phrases_old")
    cx.commit()
    return len(old)


def init_db(path=None):
    """建表。每次启动都调，靠 IF NOT EXISTS 保证不会重复建。"""
    global _conn, DB_PATH
    if path:
        DB_PATH = path
    # check_same_thread=False：托盘线程偶尔也会读一下，共用连接比每次开关更省事
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.executescript(SCHEMA)
    _conn.commit()
    _migrate_phrases(_conn)
    return _conn


def close():
    global _conn
    if _conn is not None:
        _conn.close()
        _conn = None


def _now():
    return int(time.time())


# ---------------------------------------------------------------- 历史记录

def add_history(text):
    """记一条。返回 True 表示列表需要刷新（新内容，或者旧内容被顶到了最前面）。

    用 hash 去重：同一段文字复制一百次，库里也只有一行。
    """
    if not text or not text.strip():
        return False
    if len(text) > MAX_LEN:
        return False

    h = hashlib.sha256(text.encode("utf-8", "ignore")).hexdigest()
    now = _now()

    row = _conn.execute("SELECT id FROM history WHERE hash = ?", (h,)).fetchone()
    if row:
        # 删了重插而不是只 UPDATE 时间：时间戳只到秒，同一秒里复制两段不同的字，
        # 光比 updated_at 分不出谁先谁后。插新行会让 id 递增，排序就永远确定。
        _conn.execute("DELETE FROM history WHERE id = ?", (row["id"],))
        _conn.execute(
            "INSERT INTO history (content, hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (text, h, now, now),
        )
        _conn.commit()
        return True

    _conn.execute(
        "INSERT INTO history (content, hash, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (text, h, now, now),
    )
    _conn.commit()
    return True


def list_history(keyword=None, limit=300):
    """按最后一次复制时间倒序。keyword 给了就模糊过滤。"""
    if keyword:
        rows = _conn.execute(
            "SELECT * FROM history WHERE content LIKE ? "
            "ORDER BY updated_at DESC, id DESC LIMIT ?",
            ("%" + keyword + "%", limit),
        ).fetchall()
    else:
        rows = _conn.execute(
            "SELECT * FROM history ORDER BY updated_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_history_content(item_id):
    row = _conn.execute("SELECT content FROM history WHERE id = ?", (item_id,)).fetchone()
    return row["content"] if row else ""


def delete_history(item_id):
    _conn.execute("DELETE FROM history WHERE id = ?", (item_id,))
    _conn.commit()


def clear_history():
    """只清历史，**不动常用语**。常用语是手动存的长期资产。"""
    cur = _conn.execute("DELETE FROM history")
    _conn.commit()
    return cur.rowcount


def purge_expired(days=7):
    """删掉超过 days 天没再被复制过的记录。

    判断依据是 updated_at 而不是 created_at：一段你天天在用的文字不该因为
    "第一次复制是 8 天前"就被清掉。
    """
    cutoff = _now() - days * 86400
    cur = _conn.execute("DELETE FROM history WHERE updated_at < ?", (cutoff,))
    _conn.commit()
    return cur.rowcount


# ---------------------------------------------------------------- 常用语

def add_phrase(content):
    content = (content or "").strip()
    if not content or len(content) > MAX_LEN:
        return None
    now = _now()
    cur = _conn.execute(
        "INSERT INTO phrases (content, created_at, updated_at) VALUES (?, ?, ?)",
        (content, now, now),
    )
    _conn.commit()
    return cur.lastrowid


def list_phrases(keyword=None):
    if keyword:
        rows = _conn.execute(
            "SELECT * FROM phrases WHERE content LIKE ? "
            "ORDER BY created_at ASC, id ASC",
            ("%" + keyword + "%",),
        ).fetchall()
    else:
        rows = _conn.execute("SELECT * FROM phrases ORDER BY created_at ASC, id ASC").fetchall()
    return [dict(r) for r in rows]


def get_phrase(phrase_id):
    row = _conn.execute("SELECT * FROM phrases WHERE id = ?", (phrase_id,)).fetchone()
    return dict(row) if row else None


def update_phrase(phrase_id, content):
    content = (content or "").strip()
    if not content or len(content) > MAX_LEN:
        return False
    _conn.execute(
        "UPDATE phrases SET content = ?, updated_at = ? WHERE id = ?",
        (content, _now(), phrase_id),
    )
    _conn.commit()
    return True


def delete_phrase(phrase_id):
    _conn.execute("DELETE FROM phrases WHERE id = ?", (phrase_id,))
    _conn.commit()


# ---------------------------------------------------------------- 统计

def stats():
    hist = _conn.execute("SELECT COUNT(*) c FROM history").fetchone()["c"]
    phr = _conn.execute("SELECT COUNT(*) c FROM phrases").fetchone()["c"]
    size = os.path.getsize(DB_PATH) if os.path.exists(DB_PATH) else 0
    return {"history": hist, "phrases": phr, "db_bytes": size}
