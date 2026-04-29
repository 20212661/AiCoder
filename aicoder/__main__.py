"""
AiCoder 入口点
支持 python -m aicoder 方式启动
"""
from .main import main

if __name__ == "__main__":
    import sys
    sys.exit(main())