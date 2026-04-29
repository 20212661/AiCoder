"""
AiCoder 启动脚本
可直接运行: python run.py
也可通过模块方式运行: python -m aicoder
"""
from aicoder.main import main

if __name__ == "__main__":
    import sys
    sys.exit(main())