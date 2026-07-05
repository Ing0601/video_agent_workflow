"""
ByteDanceASR - 字节跳动火山引擎语音识别服务封装

使用示例:
    asr = ByteDanceASR(app_id="your_app_id", access_token="your_token")
    result = asr.transcribe("http://example.com/audio.mp3")
    print(result)
"""

import json
import time
import uuid
import requests
import os
from typing import List, Optional, Dict, Any, Union

from .base_asr import BaseASR
from ...logger import logger


class ByteDanceASR(BaseASR):
    """字节跳动火山引擎ASR语音识别服务封装类"""
    
    def __init__(self, app_id: Optional[str] = None, access_token: Optional[str] = None):
        """
        初始化ByteDanceASR实例
        
        Args:
            app_id: 应用ID，如果不提供则从环境变量BYTEDANCE_APP_ID获取
            access_token: 访问令牌，如果不提供则从环境变量BYTEDANCE_ACCESS_TOKEN获取
        """
        super().__init__(access_token)
        
        self.app_id = app_id or os.getenv("BYTEDANCE_APP_ID")
        self.access_token = access_token or os.getenv("BYTEDANCE_ACCESS_TOKEN")
        
        if not self.app_id:
            raise ValueError("APP ID未提供，请设置app_id参数或BYTEDANCE_APP_ID环境变量")
        if not self.access_token:
            raise ValueError("Access Token未提供，请设置access_token参数或BYTEDANCE_ACCESS_TOKEN环境变量")
            
        # API URLs
        self.submit_url = "https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/submit"
        self.query_url = "https://openspeech-direct.zijieapi.com/api/v3/auc/bigmodel/query"
    
    def submit_task(self, 
                   file_url: str,
                   language: Optional[str] = None,
                   enable_channel_split: bool = True,
                   enable_ddc: bool = True,
                   enable_speaker_info: bool = True,
                   enable_punc: bool = True,
                   enable_itn: bool = True,
                   include_words: bool = False,
                   **kwargs) -> tuple[str, str]:
        """
        提交识别任务
        
        Args:
            file_url: 音频文件URL
            language: 语言设置，如 "en-US" 表示英语。为空时支持中英文、上海话、闽南语、四川话、陕西话、粤语识别
            enable_channel_split: 是否启用声道分离
            enable_ddc: 是否启用DDD
            enable_speaker_info: 是否启用说话人信息
            enable_punc: 是否启用标点符号
            enable_itn: 是否启用ITN。文本规范化 (ITN) 如，"一九七零年"->"1970年"和"一百二十三美元"->"$123"。
            include_words: 是否包含单词级别的信息
            **kwargs: 其他参数
            
        Returns:
            tuple: (task_id, x_tt_logid)
        """
        task_id = str(uuid.uuid4())
        
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "volc.bigasr.auc",
            "X-Api-Request-Id": task_id,
            "X-Api-Sequence": "-1"
        }
        
        audio_config = {
            "url": file_url,
        }
        
        # 如果指定了语言，添加到 audio 配置中
        if language:
            audio_config["language"] = language
        
        request_data = {
            "user": {
                "uid": "fake_uid"
            },
            "audio": audio_config,
            "request": {
                "model_name": "bigmodel",
                "enable_channel_split": enable_channel_split,
                "enable_ddc": enable_ddc,
                "enable_speaker_info": enable_speaker_info,
                "enable_punc": enable_punc,
                "enable_itn": enable_itn,
                "show_utterances": True,  # 总是启用utterances
                "corpus": {
                    "correct_table_name": "",
                    "context": ""
                }
            }
        }
        
        # 添加其他自定义参数
        request_data["request"].update(kwargs)
        
        logger.info(f"提交任务ID: {task_id}")
        response = requests.post(self.submit_url, data=json.dumps(request_data), headers=headers)
        
        if 'X-Api-Status-Code' in response.headers and response.headers["X-Api-Status-Code"] == "20000000":
            x_tt_logid = response.headers.get("X-Tt-Logid", "")
            logger.info(f"任务提交成功 - Status: {response.headers['X-Api-Status-Code']}")
            logger.info(f"X-Tt-Logid: {x_tt_logid}")
            return task_id, x_tt_logid
        else:
            error_msg = f"提交任务失败，响应头: {response.headers}"
            logger.error(error_msg)
            raise Exception(error_msg)
    
    def query_task(self, task_id: str, x_tt_logid: str) -> requests.Response:
        """
        查询识别任务状态
        
        Args:
            task_id: 任务ID
            x_tt_logid: 日志ID
            
        Returns:
            响应对象
        """
        headers = {
            "X-Api-App-Key": self.app_id,
            "X-Api-Access-Key": self.access_token,
            "X-Api-Resource-Id": "volc.bigasr.auc",
            "X-Api-Request-Id": task_id,
            "X-Tt-Logid": x_tt_logid
        }
        
        response = requests.post(self.query_url, data=json.dumps({}), headers=headers)
        
        if 'X-Api-Status-Code' in response.headers:
            logger.debug(f"查询任务状态 - Status: {response.headers['X-Api-Status-Code']}")
        else:
            error_msg = f"查询任务失败，响应头: {response.headers}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
        return response
    
    def transcribe(self, 
                  file_urls: Union[str, List[str]], 
                  debug: bool = False,
                  tos_config: Optional[dict] = None,
                  temp_dir: Optional[str] = None,
                  cleanup_temp: bool = True,
                  **kwargs) -> List[Dict[str, Any]]:
        """
        对音频文件进行语音识别

        支持传入：
        - 远程 URL（http/https）
        - 本地音频文件路径（mp3、wav、m4a 等）
        - 本地视频文件路径（mp4、mov 等，自动抽取音频）
        - 本地文件夹路径（自动扫描其中所有支持的媒体文件）

        传入本地文件时必须同时提供 tos_config，文件会被上传至 TOS 后再进行识别。
        
        Args:
            file_urls: 音频/视频文件 URL 或本地路径，可以是单个值或列表（支持混合）
            debug: 调试模式，为True时返回原始ASR结果，不进行处理
            tos_config: TOS 配置字典（处理本地文件时必须提供），包含：
                access_key, secret_key, endpoint, region, bucket_name
            temp_dir: ffmpeg 抽取音频时使用的临时目录，默认为项目根目录下的 temp_dir/
            cleanup_temp: 识别完成后是否自动删除 ffmpeg 生成的临时音频文件，默认 True
            **kwargs: 其他参数，如：
                - language: 语言设置，如 "en-US" 表示英语。为空时支持中英文、上海话、闽南语、四川话、陕西话、粤语识别
                - enable_channel_split: 是否启用声道分离
                - enable_ddc: 是否启用DDD
                - enable_speaker_info: 是否启用说话人信息
                - enable_punc: 是否启用标点符号
                - enable_itn: 是否启用ITN
                - include_words: 是否包含字/词级别的时间戳信息
            
        Returns:
            识别结果列表，每个元素包含文件URL和识别结果
        """
        # 预处理：本地文件/文件夹 → TOS URL
        file_urls, temp_files = self.prepare_file_urls(file_urls, tos_config, temp_dir)

        logger.info(f"开始识别 {len(file_urls)} 个音频文件")
        
        results = []
        for file_url in file_urls:
            # 提交识别任务（网络异常直接抛出，不捕获）
            task_id, x_tt_logid = self.submit_task(file_url, **kwargs)
            
            # 轮询查询任务状态（网络异常直接抛出，不捕获）
            while True:
                query_response = self.query_task(task_id, x_tt_logid)
                status_code = query_response.headers.get('X-Api-Status-Code', "")
                
                if status_code == '20000000':  # 任务完成
                    result_data = query_response.json()
                    
                    # 如果是调试模式，直接返回原始结果
                    if debug:
                        logger.info(f"调试模式：返回原始ASR结果")
                        results.append({
                            'file_url': file_url,
                            'status': 'success',
                            'transcription': result_data  # 直接返回原始数据
                        })
                    else:
                        # 处理和简化结果
                        simplified_result = self._process_result(result_data, **kwargs)
                        results.append({
                            'file_url': file_url,
                            'status': 'success',
                            'transcription': simplified_result
                        })
                    
                    logger.info(f"文件 {file_url} 识别成功")
                    break
                elif status_code != '20000001' and status_code != '20000002':  # 任务失败
                    error_data = query_response.json() if query_response.text else {}
                    results.append({
                        'file_url': file_url,
                        'status': 'failed',
                        'error': error_data
                    })
                    logger.error(f"文件 {file_url} 识别失败: {error_data}")
                    break
                else:
                    # 任务进行中，等待1秒后继续查询
                    time.sleep(1)
        
        # 清理临时文件
        if cleanup_temp and temp_files:
            for tmp in temp_files:
                try:
                    os.remove(tmp)
                    logger.debug(f"已删除临时文件: {tmp}")
                except Exception as e:
                    logger.warning(f"删除临时文件失败: {tmp}，原因: {e}")

        return results
    
    def _process_result(self, raw_result: Dict[str, Any], include_words: bool = False, enable_speaker_info: bool = True, **kwargs) -> Dict[str, Any]:
        """
        处理和简化原始识别结果
        
        Args:
            raw_result: 原始识别结果
            include_words: 是否包含单词级别的信息
            enable_speaker_info: 是否包含说话人信息
            **kwargs: 其他参数
            
        Returns:
            简化后的结果
        """
        processed_result = {
            "result": {}
        }
        
        if "result" in raw_result:
            original_result = raw_result["result"]
            processed_result["result"]["text"] = original_result.get("text", "")
            
            # 处理utterances，根据参数决定是否包含words和speaker信息
            if "utterances" in original_result:
                processed_utterances = []
                for utterance in original_result["utterances"]:
                    processed_utterance = {
                        "text": utterance.get("text", ""),
                        "start_time": utterance.get("start_time", 0),
                        "end_time": utterance.get("end_time", 0)
                    }
                    
                    # 只有在enable_speaker_info为True时才包含说话人信息
                    # 从additions字段中提取speaker信息
                    if enable_speaker_info:
                        additions = utterance.get("additions", {})
                        if "speaker" in additions:
                            processed_utterance["speaker"] = additions["speaker"]
                    
                    # 只有在include_words为True时才包含words信息
                    if include_words and "words" in utterance:
                        processed_utterance["words"] = utterance["words"]
                    
                    processed_utterances.append(processed_utterance)
                
                processed_result["result"]["utterances"] = processed_utterances
        
        # 从原始结果中获取音频时长
        audio_duration = raw_result.get("audio_info", {}).get("duration", 0)
        
        usage = {
            "model": "bytedance-big-model-asr",
            "total_duration_ms": audio_duration,
        }
        processed_result["usage"] = usage
        
        return processed_result