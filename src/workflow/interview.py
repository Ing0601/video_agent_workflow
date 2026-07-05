# 要构造一个处理访谈类视频

from ..logger.logging import logger
from ..node.asr_transcribe import ASRTranscriber
from ..node.content_clipper import ContentClipper
from ..node.interview_highlight import InterviewHighlight

class InterviewWorkflow:

    def __init__(self):
        """初始化工作流"""
        self.logger = logger
        self._asr_transcriber = ASRTranscriber()  # ASR转录节点
        self._content_clipper = ContentClipper()  # 内容切片节点
        self._interview_highlight = InterviewHighlight()  # 访谈精华分析节点

    def _process_single_video(self, video_path: str):
        """处理单个视频"""
        try:
            # 步骤1： ASR识别
            self.logger.info(f"\n[步骤 1/3] 开始ASR识别...")
            asr_result = self._asr_transcriber.transcribe_video(video_path)
            if not asr_result["success"]:
                raise Exception(f"ASR识别失败: {asr_result.get('error')}")
            
            # 步骤2： 话题切分
            self.logger.info(f"\n[步骤 2/3] 开始话题切分...")
            topic_result = self._content_clipper.generate_slices(
                utterances=asr_result["utterances"],
                system_prompt=self._build_topic_system_prompt(),
            )

            # 步骤3： 精华音频理解分析
            self.logger.info(f"\n[步骤 3/3] 开始精华音频理解分析...")
            highlight_result = self._interview_highlight.highlight_audio_content(
                goal_duration=300,  # 默认5分钟，可由外部传入
                system_prompt=self._build_highlight_system_prompt(),
                utterances=asr_result["utterances"],
                topic_slices=topic_result.get("slices") if topic_result.get("success") else None,
            )
            if not highlight_result["success"]:
                raise Exception(f"精华分析失败: {highlight_result.get('error')}")
        except Exception as e:
            self.logger.error(f"处理视频失败: {e}")
            raise e
        return asr_result, topic_result, highlight_result

    def _build_topic_system_prompt(self) -> str:
        """构建话题切分的系统提示词"""
        return """
# 角色
你是一位资深的访谈类视频内容分析专家，擅长从对话文本中识别语义边界、提炼核心议题。

# 任务
将访谈字幕按照语义话题进行切片，要求每个切片对应一个独立、连贯的讨论主题，
并对每个切片的内容进行精炼总结。

# 输入格式
JSON 数组，每个元素包含：
- start: 开始时间（秒，浮点数）
- end: 结束时间（秒，浮点数）
- text: 字幕文本
- speaker: 说话人标识（如有）

# 执行步骤

## Step 1：通读全文，建立话题地图
通读所有字幕，识别访谈中出现的所有独立议题。

判断话题边界的标准：
- 讨论对象发生明显切换（如从"产品"转向"团队"）
- 说话人的视角或立场出现转变
- 主持人提出新的问题引导话题跳转
- 前后内容无法用同一个名词短语概括

忽略以下内容对话题边界的干扰：
- 主持人的简短追问、确认语（"对对对"、"然后呢"、"嗯"）
- 受访者的口头禅、填充词
- 话题内部的短暂停顿或举例插叙

## Step 2：确定时间边界
- 每个话题的 start 取该话题第一句字幕的 start 值
- 每个话题的 end 取该话题最后一句字幕的 end 值
- 相邻话题必须严格首尾相接：上一个话题的 end 与下一个话题的 start 数值完全一致
- 第一个话题的 start == 输入中最小的 start 值
- 最后一个话题的 end == 输入中最大的 end 值
- 不允许出现时间重叠，不允许出现时间空隙

## Step 3：过渡内容归属
相邻话题之间可能存在过渡性内容（如主持人承上启下的提问、嘉宾的话题收尾语）。
此类内容不单独成片，按以下规则决定归属，归属后仍保持首尾相接：

1. 若过渡内容在语义上**结束**了上一个话题（如总结性陈述、感慨收尾）→ 归入上一个话题
2. 若过渡内容在语义上**开启**了下一个话题（如主持人引出新问题、嘉宾主动转换话题）→ 归入下一个话题
3. 若过渡内容承上启下、两者皆有：
   - 能以句子为单位拆分时：前半句归上一话题，后半句归下一话题
   - 同一句话无法拆分时：统一归入下一个话题

## Step 4：撰写话题总结
对每个切片的内容进行总结，要求：
- 20-60 字，语言简洁客观
- 使用陈述句，概括"讲了什么"而非"说了哪些话"
- 包含关键信息点（核心观点、数据、人名、事件等）
- 不出现"受访者表示"、"嘉宾提到"等冗余表述，直接陈述内容

## Step 5：粒度自检
输出前检查以下条件，不满足则重新调整切分：
- 话题数量：每 10 分钟视频对应 3-6 个话题（过多说明切得太细，过少说明合并过度）
- 最短时长：每个话题建议不低于 60 秒（开场寒暄、结尾致谢等特殊段落除外）
- 若某话题时长不足 30 秒，必须并入语义最近的相邻话题
- 首尾检查：第一条 start == 输入最小 start，最后一条 end == 输入最大 end
- 连续性检查：逐条确认每条 end == 下一条 start，不存在空隙或重叠

# 输出格式
严格输出以下 JSON 格式，能被 Python json.loads() 直接解析：

[
  {
    "start": 0.00,
    "end": 183.40,
    "content": "话题内容总结，20-60字。"
  },
  {
    "start": 183.40,
    "end": 412.80,
    "content": "话题内容总结，20-60字。"
  }
]

注意：
- start 和 end 为数字类型，不加引号
- 不输出任何 JSON 以外的内容（无前缀说明、无 markdown 代码块标记）
- 相邻条目的 end 与下一条 start 数值必须完全一致
"""
    def _build_highlight_system_prompt(self) -> str:
        """构建精华音频理解分析的系统提示词"""
        return """
# 角色
你是一位资深的访谈类视频内容分析专家，擅长从访谈对话中识别最具价值的精华片段。

# 任务
从访谈字幕中识别出最具价值、最精彩的片段，生成精华视频。

# 目标
根据用户指定的目标精华时长，从访谈中筛选出最有价值的片段组合，使总时长接近目标时长。

# 输入格式
ASR 字幕文本 JSON 数组，每个元素包含：
- start: 开始时间（秒，浮点数）
- end: 结束时间（秒，浮点数）
- text: 字幕文本
- speaker: 说话人标识（如有）

可选输入：话题切分结果 JSON 数组，每个元素包含：
JSON 数组，每个元素包含：
- start: 话题开始时间
- end: 话题结束时间
- content: 话题内容总结

# 精华片段筛选标准

## 高价值内容
- 核心观点输出：受访者阐述的重要观点、理念、原则
- 精彩回答：针对关键问题的深度回答
- 有趣故事：分享的亲身经历、案例、轶事
- 独特见解：与众不同的视角或洞察
- 情感表达：真诚的情感流露或重要表态
- 金句频出：密集输出观点或信息的段落
- 主持人追问：对重要话题的深入探讨
- 互动亮点：双方有来有往的深入交流

## 低价值内容（尽量避免选入）
- 开场寒暄：初次见面、相互认识的客套话
- 结尾致谢：感谢受访者、观众告别
- 过渡性提问：承上启下但无实质内容的连接语
- 重复内容：已经表达过的观点再次重复
- 离题内容：与访谈主题无关的内容
- 设备/技术问题：音频卡顿、环境噪音等技术性说明
- 填充词：嗯、啊、这个、就是等口头禅

# 执行步骤

## Step 1：通读全文，理解访谈结构
快速浏览所有字幕，了解：
- 访谈的主题和背景
- 主持人问了哪些核心问题
- 受访者回答了哪些重要观点

## Step 2：识别高价值片段
标记所有符合"高价值内容"标准的片段。

## Step 3：计算目标时长
根据用户提供的目标精华时长（goal_duration），合理选择片段组合：
- 优先选择价值最高的片段
- 多个短片段可以组合成一个较长的精华段
- 确保选中的片段总时长接近目标时长
- 片段之间可以有间隔（跳过低价值内容）

## Step 4：确定时间边界
- 每个精华片段的 start 取该片段第一句字幕的 start 值
- 每个精华片段的 end 取该片段最后一句字幕的 end 值
- 允许片段之间存在时间间隔（跳过低价值内容）

## Step 5：撰写片段描述
对每个精华片段撰写简短的描述（20-40字），要求：
- 概括片段的核心内容
- 突出片段的亮点和价值
- 语言简洁客观

# 输出格式
严格输出以下 JSON 格式，能被 Python json.loads() 直接解析：

[
  {
    "start": 0.00,
    "end": 45.50,
    "duration": 45.50,
    "content": "精华片段描述，20-40字。"
  },
  {
    "start": 183.40,
    "end": 289.20,
    "duration": 105.80,
    "content": "精华片段描述，20-40字。"
  }
]

注意：
- start 和 end 为数字类型，不加引号
- 不输出任何 JSON 以外的内容（无前缀说明、无 markdown 代码块标记）
- 片段之间允许存在时间间隔
- 精华片段总时长应接近目标时长
"""

