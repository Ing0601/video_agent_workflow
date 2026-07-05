import sys
import subprocess
import logging
from typing import List, Optional, Dict, Any

def get_subprocess_kwargs() -> Dict[str, Any]:
    """获取 subprocess 的通用参数，包括 Windows 下隐藏窗口的设置"""
    kwargs = {}
    if sys.platform == 'win32':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        kwargs['startupinfo'] = startupinfo
        if sys.version_info >= (3, 7):
            kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    return kwargs

def run_command(
    cmd: List[str], 
    timeout: Optional[float] = None, 
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    **kwargs
) -> subprocess.CompletedProcess:
    """
    运行命令，封装了隐藏窗口和进程管理逻辑。
    类似 subprocess.run，但使用 Popen 实现以确保更好的进程控制。
    
    Args:
        cmd: 命令列表
        timeout: 超时时间（秒）
        check: 如果返回码非零是否抛出异常
        capture_output: 是否捕获输出
        text: 是否以文本模式返回输出 (同 universal_newlines)
        **kwargs: 传递给 subprocess.Popen 的其他参数
    
    Returns:
        subprocess.CompletedProcess 对象
    """
    
    # 合并默认的隐藏窗口参数
    popen_kwargs = get_subprocess_kwargs()
    # 用户传入的参数覆盖默认参数
    popen_kwargs.update(kwargs)
    
    # 设置输出捕获
    if capture_output:
        if 'stdout' not in popen_kwargs:
            popen_kwargs['stdout'] = subprocess.PIPE
        if 'stderr' not in popen_kwargs:
            popen_kwargs['stderr'] = subprocess.PIPE
            
    if text:
        popen_kwargs['text'] = True
        
    process = subprocess.Popen(cmd, **popen_kwargs)
    
    try:
        stdout, stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(process.args, timeout, output=stdout, stderr=stderr)
    except Exception:
        process.kill()
        raise
    finally:
        # 确保进程已关闭
        if process.poll() is None:
            process.kill()
            process.wait()
            
    retcode = process.poll()
    
    if check and retcode != 0:
        raise subprocess.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
        
    return subprocess.CompletedProcess(process.args, retcode, stdout, stderr)
