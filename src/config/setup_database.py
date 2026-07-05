from pathlib import Path
from typing import Dict, Any
import os, sys
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(PROJECT_ROOT))

from src.logger.logging import logger, LogConfig

LogConfig.init_logger()

def read_schema_file(schema_file: str = None) -> str:
    if schema_file is None:
        schema_file = Path(__file__).resolve().parent.parent.parent / "schema.sql"
    
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    with open(schema_file, "r", encoding="utf-8") as f:
        return f.read()

def parse_database_url(db_url: str) -> Dict[str, Any]:
    """解析数据库连接url"""
    # URL解析格式: mysql+pymysql://root:123456@localhost:3306/video_agent
    if not db_url.startswith("mysql"):
        raise ValueError("仅支持MySQL数据库")
    
    # 移除协议前缀
    db_url = db_url.split("://",1)[1]

    # 分离认证和地址部分
    auth_part, host_part = db_url.split("@", 1)
    username, password = auth_part.split(":", 1) if ":" in auth_part else (auth_part, None)

    if "/" in host_part:
        host_port, database = host_part.split("/", 1)
    else:
        host_port, database = host_part, ""
    
    if ":" in host_port:
        host, port = host_port.split(":", 1)
        port = int(port)
    else: 
        host, port = host_port, 3306
    
    return {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "password": password,
    }

def setup_database():
    """设置数据库"""
    logger.info("开始设置数据库")

    # 读取环境变量
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.info("未找到数据库连接URL")
        logger.info(
            "示例: export DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/video_agent"
        )
        return False
    
    try:
        import pymysql
        import pymysql.cursors

        # 解析数据库url
        db_config = parse_database_url(db_url)

        logger.info(f"数据库配置: 主机: {db_config['host']}:{db_config['port']}; 用户: {db_config['username']}; 数据库: {db_config['database']}")

        logger.info("连接数据库...")
        conn = pymysql.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['username'],
            password=db_config['password'],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )

        try:
            with conn.cursor() as cursor:
                # 创建数据库 (如果不存在)
                if db_config["database"]:
                    cursor.execute(
                        f"""
                        CREATE DATABASE IF NOT EXISTS `{db_config["database"]}`
                        CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
                        """
                    )

                    # 切换到目标数据库
                    cursor.execute(f"USE `{db_config['database']}`")
            conn.commit()
        finally:
            conn.close()

        logger.info("连接到目标数据库......")
        conn = pymysql.connect(
            host=db_config['host'],
            port=db_config['port'],
            user=db_config['username'],
            password=db_config['password'],
            database=db_config['database'],
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
        )

        try:
            # 读取并执行schema.sql文件
            logger.info("读取表结构文件...")
            sql_content = read_schema_file()

            logger.info("创建表结构...")
            with conn.cursor() as cursor:
                # 分割并执行每个SQL语句
                statements = [
                    stmt.strip() for stmt in sql_content.split(";") if stmt.strip()
                ]

                for i, statement in enumerate(statements, 1):
                    try:
                        cursor.execute(statement)
                        # 提取表名用于显示
                        # if "CREATE TABLE" in statement.upper():
                        #     table_start = statement.upper().find("CREATE TABLE")
                        #     table_part = statement[table_start:].split("(")[0]
                        #     table_name = table_part.split()[-1].strip("`")
                        #     logger.info(f"创建表：{table_name}")
                    except Exception as e:
                        logger.error(f"执行第{i}个SQL语句失败: {e}")
                        raise e
            
            conn.commit()
            logger.info("数据库表结构创建成功")

            logger.info("验证表结构...")
            with conn.cursor() as cursor:
                cursor.execute("SHOW TABLES")
                tables = cursor.fetchall()

                expected_tables = ["sessions", "events", "messages"]
                found_tables = [
                    table for row in tables for table in row.values() if table in expected_tables
                ]

                if found_tables:
                    logger.info(f"已创建表: {', '.join(found_tables)}")
                    for table in sorted(found_tables):
                        cursor.execute(f"SELECT COUNT(*) as count FROM {table}")
                        count = cursor.fetchone()["count"]
                        logger.info(f" - {table} ({count} rows)")
                else:
                    logger.info("未创建预期的表")
                    return False
        finally:
            conn.close()

    except Exception as e:
        logger.error(f"设置数据库失败: {e}")
        return False

if __name__ == "__main__":
    setup_database()
    # print(parse_database_url("mysql+pymysql://root:123456@localhost:3306/video_agent"))

# def setup_database(db_url: str) -> None:
#     engine = create_engine(db_url)
#     with engine.connect() as conn:
#         conn.execute(text(read_schema_file()))
