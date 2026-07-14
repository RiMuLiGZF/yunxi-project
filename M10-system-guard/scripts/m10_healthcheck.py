"""
M10 系统卫士 - 健康检查脚本

快速检查 M10 服务状态、数据库、核心功能。
用法: python scripts/m10_healthcheck.py [--port 8010]
"""
import sys
import os
import time
import json
import requests
import argparse

def main():
    parser = argparse.ArgumentParser(description='M10 系统卫士健康检查')
    parser.add_argument('--port', type=int, default=8010, help='服务端口')
    parser.add_argument('--host', type=str, default='localhost', help='服务主机')
    args = parser.parse_args()

    base_url = f'http://{args.host}:{args.port}'
    results = {'timestamp': time.time(), 'checks': {}}

    # 1. 服务连通性
    try:
        r = requests.get(f'{base_url}/health', timeout=5)
        results['checks']['service'] = {'status': 'ok', 'version': r.json().get('data', {}).get('version', 'unknown')}
    except Exception as e:
        results['checks']['service'] = {'status': 'error', 'message': str(e)}
        print(json.dumps(results, indent=2, ensure_ascii=False))
        sys.exit(1)

    # 2. 数据库检查
    try:
        db_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'yunxi_m10.db')
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        results['checks']['database'] = {'status': 'ok', 'size_mb': round(db_size / 1024 / 1024, 2)}
    except Exception as e:
        results['checks']['database'] = {'status': 'error', 'message': str(e)}

    # 3. 核心指标检查
    try:
        r = requests.get(f'{base_url}/api/v1/status/summary', timeout=5)
        data = r.json().get('data', {})
        cpu = data.get('cpu', {}).get('usage_percent', 0)
        mem = data.get('memory', {}).get('usage_percent', 0)
        results['checks']['metrics'] = {'status': 'ok', 'cpu': cpu, 'memory': mem}
    except Exception as e:
        results['checks']['metrics'] = {'status': 'error', 'message': str(e)}

    # 汇总
    all_ok = all(c['status'] == 'ok' for c in results['checks'].values())
    results['overall'] = 'healthy' if all_ok else 'degraded'

    print(json.dumps(results, indent=2, ensure_ascii=False))
    sys.exit(0 if all_ok else 1)

if __name__ == '__main__':
    main()
