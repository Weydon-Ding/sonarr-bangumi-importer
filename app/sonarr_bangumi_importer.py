'''
Sonarr Bangumi Importer
通过Bangumi API获取观看列表，并通过Sonarr API查询剧集的TVDB ID
并缓存到SQLite数据库中
'''

import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import requests
import yaml
from flask import Flask, jsonify
from flask.logging import default_handler

# 初始化应用
app = Flask(__name__)
app.config['JSON_AS_ASCII'] = False
app.logger.removeHandler(default_handler)

# 加载配置文件
CONFIG_FILE = Path('/app/config.yaml')  # Docker容器内路径

def load_config() -> dict:
    """从YAML文件加载配置"""
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        app.logger.error(f"加载配置文件失败: {str(e)}")
        raise

CONFIG = load_config()

# 数据库初始化
def init_db() -> None:
    """初始化数据库表"""
    with sqlite3.connect(CONFIG['database']['path']) as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS tvdb_cache (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        series_name TEXT UNIQUE,
                        tvdb_id INTEGER,
                        created_at DATETIME)''')

init_db()

class TVDBCache:
    """TVDB ID 缓存处理器"""

    @staticmethod
    def get(series_name: str) -> Optional[int]:
        """获取缓存中的TVDB ID"""
        with sqlite3.connect(CONFIG['database']['path']) as conn:
            cursor = conn.execute(
                'SELECT tvdb_id, created_at FROM tvdb_cache WHERE series_name = ?',
                (series_name,)
            )
            result = cursor.fetchone()

        if result and datetime.fromisoformat(result[1]) > datetime.now() - timedelta(
            days=CONFIG['cache']['expire_days']
        ):
            return int(result[0])
        return None

    @staticmethod
    def set(series_name: str, tvdb_id: int) -> None:
        """更新缓存记录"""
        with sqlite3.connect(CONFIG['database']['path']) as conn:
            conn.execute('''REPLACE INTO tvdb_cache
                          (series_name, tvdb_id, created_at)
                          VALUES (?, ?, ?)''',
                         (series_name, tvdb_id, datetime.now().isoformat()))
            conn.commit()

def lookup_series_by_name(series_name: str) -> int:
    """通过Sonarr API查询剧集TVDB ID"""
    # 先尝试读取缓存
    if cached_id := TVDBCache.get(series_name):
        return cached_id

    headers = {"X-Api-Key": CONFIG['sonarr']['api_key']}
    params = {"term": series_name}

    try:
        response = requests.get(
            f"{CONFIG['sonarr']['url']}/api/v3/series/lookup",
            params=params,
            headers=headers,
            timeout=60
        )
        response.raise_for_status()

        if not (results := response.json()):
            app.logger.warning(f"未找到剧集: {series_name}")
            return 0

        tvdb_id = results[0]['tvdbId']
        TVDBCache.set(series_name, tvdb_id)  # 更新缓存
        return tvdb_id

    except requests.exceptions.RequestException as e:
        app.logger.error(f"Sonarr API请求失败: {str(e)}")
        return 0

def get_bgm_collection() -> List[Dict[str, str]]:
    """获取Bangumi观看列表数据"""
    try:
        response = requests.get(
            f'https://api.bgm.tv/user/{CONFIG["bangumi"]["user_id"]}/collection',
            params={'cat': 'watching'},
            headers={'User-Agent': "Sonarr Custom List/1.0"},
            timeout=10
        )
        response.raise_for_status()
        return [{
            "title": item['name'],
            "tvdbId": lookup_series_by_name(item['name'])
        } for item in response.json()]

    except Exception as e:
        app.logger.error(f"Bangumi API请求失败: {str(e)}")
        return []

@app.route('/watching-list', methods=['GET'])
def get_list():
    """自定义列表接口"""
    return jsonify(get_bgm_collection())

if __name__ == '__main__':
    # 初始化日志
    logging.basicConfig(
        level=CONFIG['log']['level'],
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    app.run(
        host=CONFIG['server']['host'],
        port=CONFIG['server']['port'],
        debug=CONFIG['server']['debug']
    )
