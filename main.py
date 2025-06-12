# coding=utf-8

import json
import time
import random
from datetime import datetime
import webbrowser
from typing import Dict, List, Tuple, Optional, Union
from pathlib import Path
import os

import requests
import pytz

# 配置常量
CONFIG = {
    "FEISHU_SEPARATOR": "━━━━━━━━━━━━━━━━━━━",  # 飞书消息分割线，注意，其它类型的分割线可能会被飞书过滤而不显示
    "REQUEST_INTERVAL": 1000,  # 请求间隔(毫秒)
    "FEISHU_REPORT_TYPE": "daily",  # 飞书报告类型: "current"|"daily"|"both"
    "RANK_THRESHOLD": 5,  # 排名高亮阈值
    "USE_PROXY": True,  # 是否启用代理
    "DEFAULT_PROXY": "http://127.0.0.1:10086",
    "CONTINUE_WITHOUT_FEISHU": True,  # 控制在没有飞书 webhook URL 时是否继续执行爬虫, 如果 True ,会依然进行爬虫行为，并在 github 上持续的生成爬取的新闻数据
    "FEISHU_WEBHOOK_URL": "",  # 飞书机器人的 webhook URL，大概长这样：https://www.feishu.cn/flow/api/trigger-webhook/xxxx， 默认为空，推荐通过GitHub Secrets设置
}


class TimeHelper:
    """时间处理工具"""

    @staticmethod
    def get_beijing_time() -> datetime:
        """获取北京时间"""
        return datetime.now(pytz.timezone("Asia/Shanghai"))

    @staticmethod
    def format_date_folder() -> str:
        """返回日期文件夹格式"""
        return TimeHelper.get_beijing_time().strftime("%Y年%m月%d日")

    @staticmethod
    def format_time_filename() -> str:
        """返回时间文件名格式"""
        return TimeHelper.get_beijing_time().strftime("%H时%M分")


class FileHelper:
    """文件操作工具"""

    @staticmethod
    def ensure_directory_exists(directory: str) -> None:
        """确保目录存在"""
        Path(directory).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def get_output_path(subfolder: str, filename: str) -> str:
        """获取输出文件路径"""
        date_folder = TimeHelper.format_date_folder()
        output_dir = Path("output") / date_folder / subfolder
        FileHelper.ensure_directory_exists(str(output_dir))
        return str(output_dir / filename)


class DataFetcher:
    """数据获取器"""

    def __init__(self, proxy_url: Optional[str] = None):
        self.proxy_url = proxy_url

    def fetch_data(
        self,
        id_info: Union[str, Tuple[str, str]],
        max_retries: int = 2,
        min_retry_wait: int = 3,
        max_retry_wait: int = 5,
    ) -> Tuple[Optional[str], str, str]:
        """获取指定ID数据，支持重试"""
        # 解析ID和别名
        if isinstance(id_info, tuple):
            id_value, alias = id_info
        else:
            id_value = id_info
            alias = id_value

        url = f"https://newsnow.busiyi.world/api/s?id={id_value}&latest"

        # 设置代理
        proxies = None
        if self.proxy_url:
            proxies = {"http": self.proxy_url, "https": self.proxy_url}

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
            "Cache-Control": "no-cache",
        }

        retries = 0
        while retries <= max_retries:
            try:
                print(f"正在请求 {id_value} 数据... (尝试 {retries + 1}/{max_retries + 1})")
                response = requests.get(url, proxies=proxies, headers=headers, timeout=10)
                response.raise_for_status()

                data_text = response.text
                data_json = json.loads(data_text)

                # 检查响应状态，接受success和cache
                status = data_json.get("status", "未知")
                if status not in ["success", "cache"]:
                    raise ValueError(f"响应状态异常: {status}")

                status_info = "最新数据" if status == "success" else "缓存数据"
                print(f"成功获取 {id_value} 数据（{status_info}）")
                return data_text, id_value, alias

            except Exception as e:
                retries += 1
                if retries <= max_retries:
                    # 计算重试等待时间：基础时间+递增时间
                    base_wait = random.uniform(min_retry_wait, max_retry_wait)
                    additional_wait = (retries - 1) * random.uniform(1, 2)
                    wait_time = base_wait + additional_wait

                    print(f"请求 {id_value} 失败: {e}. 将在 {wait_time:.2f} 秒后重试...")
                    time.sleep(wait_time)
                else:
                    print(f"请求 {id_value} 失败: {e}. 已达到最大重试次数。")
                    return None, id_value, alias
        return None, id_value, alias

    def crawl_websites(
        self,
        ids_list: List[Union[str, Tuple[str, str]]],
        request_interval: int = CONFIG["REQUEST_INTERVAL"],
    ) -> Tuple[Dict, Dict, List]:
        """爬取多个网站数据"""
        results = {}
        id_to_alias = {}
        failed_ids = []

        for i, id_info in enumerate(ids_list):
            # 解析ID和别名
            if isinstance(id_info, tuple):
                id_value, alias = id_info
            else:
                id_value = id_info
                alias = id_value

            id_to_alias[id_value] = alias

            # 获取数据
            response, _, _ = self.fetch_data(id_info)

            if response:
                try:
                    data = json.loads(response)
                    results[id_value] = {}
                    for index, item in enumerate(data.get("items", []), 1):
                        title = item["title"]
                        url = item.get("url", "")
                        mobile_url = item.get("mobileUrl", "")
                    
                        if title in results[id_value]:
                            # 标题已存在，更新排名
                            results[id_value][title]["ranks"].append(index)
                        else:
                            # 新标题
                            results[id_value][title] = {
                                "ranks": [index],
                                "url": url,
                                "mobileUrl": mobile_url
                            }
                except json.JSONDecodeError:
                    print(f"解析 {id_value} 响应失败，非有效JSON")
                    failed_ids.append(id_value)
                except Exception as e:
                    print(f"处理 {id_value} 数据出错: {e}")
                    failed_ids.append(id_value)
            else:
                failed_ids.append(id_value)

            # 添加请求间隔
            if i < len(ids_list) - 1:
                actual_interval = request_interval + random.randint(-10, 20)
                actual_interval = max(50, actual_interval)  # 最少50毫秒
                print(f"等待 {actual_interval} 毫秒后发送下一个请求...")
                time.sleep(actual_interval / 1000)

        print(f"\n请求总结:")
        print(f"- 成功获取数据: {list(results.keys())}")
        print(f"- 请求失败: {failed_ids}")

        return results, id_to_alias, failed_ids


class DataProcessor:
    """数据处理器"""

    @staticmethod
    def save_titles_to_file(results: Dict, id_to_alias: Dict, failed_ids: List) -> str:
        """保存标题到文件"""
        file_path = FileHelper.get_output_path("txt", f"{TimeHelper.format_time_filename()}.txt")

        with open(file_path, "w", encoding="utf-8") as f:
            # 写入成功数据
            for id_value, title_data in results.items():
                display_name = id_to_alias.get(id_value, id_value)
                f.write(f"{display_name}\n")
                for i, (title, info) in enumerate(title_data.items(), 1):
                    if isinstance(info, dict):
                        ranks = info.get("ranks", [])
                        url = info.get("url", "")
                        mobile_url = info.get("mobileUrl", "")
                        rank_str = ",".join(map(str, ranks))
                        line = f"{i}. {title} (排名:{rank_str})"
                        if url:
                            line += f" [URL:{url}]"
                        if mobile_url:
                            line += f" [MOBILE:{mobile_url}]"
                        f.write(line + "\n")
                    else:
                        # 兼容旧格式
                        rank_str = ",".join(map(str, info))
                        f.write(f"{i}. {title} (排名:{rank_str})\n")
                f.write("\n")

            # 写入失败信息
            if failed_ids:
                f.write("==== 以下ID请求失败 ====\n")
                for id_value in failed_ids:
                    display_name = id_to_alias.get(id_value, id_value)
                    f.write(f"{display_name} (ID: {id_value})\n")

        return file_path

    @staticmethod
    def load_frequency_words(frequency_file: str = "frequency_words.txt") -> Tuple[List[Dict], List[str]]:
        """加载频率词配置"""
        frequency_path = Path(frequency_file)
        if not frequency_path.exists():
            print(f"频率词文件 {frequency_file} 不存在")
            return [], []

        with open(frequency_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 按双空行分割词组
        word_groups = [group.strip() for group in content.split("\n\n") if group.strip()]

        processed_groups = []
        filter_words = []

        for group in word_groups:
            words = [word.strip() for word in group.split("\n") if word.strip()]

            # 分类词汇
            group_required_words = []  # +开头必须词
            group_normal_words = []    # 普通频率词
            group_filter_words = []    # !开头过滤词

            for word in words:
                if word.startswith("!"):
                    filter_words.append(word[1:])
                    group_filter_words.append(word[1:])
                elif word.startswith("+"):
                    group_required_words.append(word[1:])
                else:
                    group_normal_words.append(word)

            # 只处理包含有效词的组
            if group_required_words or group_normal_words:
                # 生成组标识
                if group_normal_words:
                    group_key = " ".join(group_normal_words)
                else:
                    group_key = " ".join(group_required_words)

                processed_groups.append({
                    'required': group_required_words,
                    'normal': group_normal_words,
                    'group_key': group_key
                })

        return processed_groups, filter_words

    @staticmethod
    def read_all_today_titles() -> Tuple[Dict, Dict, Dict]:
        """读取当天所有标题文件"""
        date_folder = TimeHelper.format_date_folder()
        txt_dir = Path("output") / date_folder / "txt"

        if not txt_dir.exists():
            print(f"今日文件夹 {txt_dir} 不存在")
            return {}, {}, {}

        all_results = {}
        id_to_alias = {}
        title_info = {}

        # 按时间排序处理文件
        files = sorted([f for f in txt_dir.iterdir() if f.suffix == ".txt"])

        for file_path in files:
            time_info = file_path.stem
            
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

                sections = content.split("\n\n")
                for section in sections:
                    if not section.strip() or "==== 以下ID请求失败 ====" in section:
                        continue

                    lines = section.strip().split("\n")
                    if len(lines) < 2:
                        continue

                    source_name = lines[0].strip()

                    # 解析标题数据
                    title_data = {}
                    for line in lines[1:]:
                        if line.strip():
                            try:
                                match_num = None
                                title_part = line.strip()

                                # 提取序号
                                if ". " in title_part and title_part.split(". ")[0].isdigit():
                                    parts = title_part.split(". ", 1)
                                    match_num = int(parts[0])
                                    title_part = parts[1]

                                # 提取mobileUrl
                                mobile_url = ""
                                if " [MOBILE:" in title_part:
                                    title_part, mobile_part = title_part.rsplit(" [MOBILE:", 1)
                                    if mobile_part.endswith("]"):
                                        mobile_url = mobile_part[:-1]

                                # 提取url
                                url = ""
                                if " [URL:" in title_part:
                                    title_part, url_part = title_part.rsplit(" [URL:", 1)
                                    if url_part.endswith("]"):
                                        url = url_part[:-1]

                                # 提取排名
                                ranks = []
                                if " (排名:" in title_part:
                                    title, rank_str = title_part.rsplit(" (排名:", 1)
                                    rank_str = rank_str.rstrip(")")
                                    ranks = [int(r) for r in rank_str.split(",") if r.strip() and r.isdigit()]
                                else:
                                    title = title_part

                                if not ranks and match_num is not None:
                                    ranks = [match_num]
                                if not ranks:
                                    ranks = [99]

                                title_data[title] = {
                                    "ranks": ranks,
                                    "url": url,
                                    "mobileUrl": mobile_url
                                }

                            except Exception as e:
                                print(f"解析标题行出错: {line}, 错误: {e}")

                    DataProcessor._process_source_data(
                        source_name, title_data, time_info,
                        all_results, title_info, id_to_alias
                    )

        # 转换为ID结果
        id_results = {}
        id_title_info = {}
        for name, titles in all_results.items():
            for id_value, alias in id_to_alias.items():
                if alias == name:
                    id_results[id_value] = titles
                    id_title_info[id_value] = title_info[name]
                    break

        return id_results, id_to_alias, id_title_info

    @staticmethod
    def _process_source_data(
        source_name: str, title_data: Dict, time_info: str,
        all_results: Dict, title_info: Dict, id_to_alias: Dict,
    ) -> None:
        """处理来源数据，合并重复标题"""
        if source_name not in all_results:
            # 首次遇到此来源
            all_results[source_name] = title_data

            if source_name not in title_info:
                title_info[source_name] = {}

            # 记录标题信息
            for title, data in title_data.items():
                if isinstance(data, dict):
                    ranks = data.get("ranks", [])
                    url = data.get("url", "")
                    mobile_url = data.get("mobileUrl", "")
                else:
                    ranks = data if isinstance(data, list) else []
                    url = ""
                    mobile_url = ""

                title_info[source_name][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }

            # 生成反向ID映射
            reversed_id = source_name.lower().replace(" ", "-")
            id_to_alias[reversed_id] = source_name
        else:
            # 更新已有来源
            for title, data in title_data.items():
                if isinstance(data, dict):
                    ranks = data.get("ranks", [])
                    url = data.get("url", "")
                    mobile_url = data.get("mobileUrl", "")
                else:
                    ranks = data if isinstance(data, list) else []
                    url = ""
                    mobile_url = ""

                if title not in all_results[source_name]:
                    # 新标题
                    all_results[source_name][title] = {
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url
                    }
                    title_info[source_name][title] = {
                        "first_time": time_info,
                        "last_time": time_info,
                        "count": 1,
                        "ranks": ranks,
                        "url": url,
                        "mobileUrl": mobile_url,
                    }
                else:
                    # 更新已有标题
                    existing_data = all_results[source_name][title]
                    existing_ranks = existing_data.get("ranks", [])
                    existing_url = existing_data.get("url", "")
                    existing_mobile_url = existing_data.get("mobileUrl", "")
                
                    merged_ranks = existing_ranks.copy()
                    for rank in ranks:
                        if rank not in merged_ranks:
                            merged_ranks.append(rank)

                    all_results[source_name][title] = {
                        "ranks": merged_ranks,
                        "url": existing_url or url,
                        "mobileUrl": existing_mobile_url or mobile_url
                    }

                    title_info[source_name][title]["last_time"] = time_info
                    title_info[source_name][title]["ranks"] = merged_ranks
                    title_info[source_name][title]["count"] += 1
                    # 保留第一个有效URL
                    if not title_info[source_name][title].get("url"):
                        title_info[source_name][title]["url"] = url
                    if not title_info[source_name][title].get("mobileUrl"):
                        title_info[source_name][title]["mobileUrl"] = mobile_url


class StatisticsCalculator:
    """统计计算器"""

    @staticmethod
    def count_word_frequency(
        results: Dict,
        word_groups: List[Dict],
        filter_words: List[str],
        id_to_alias: Dict,
        title_info: Optional[Dict] = None,
        rank_threshold: int = CONFIG["RANK_THRESHOLD"],
    ) -> Tuple[List[Dict], int]:
        """统计词频，支持必须词、频率词、过滤词"""
        word_stats = {}
        total_titles = 0
        processed_titles = {}  # 跟踪已处理标题

        if title_info is None:
            title_info = {}

        # 初始化统计对象
        for group in word_groups:
            group_key = group['group_key']
            word_stats[group_key] = {"count": 0, "titles": {}}

        # 遍历标题进行统计
        for source_id, titles_data in results.items():
            total_titles += len(titles_data)

            if source_id not in processed_titles:
                processed_titles[source_id] = {}

            for title, title_data in titles_data.items():
                if title in processed_titles.get(source_id, {}):
                    continue

                title_lower = title.lower()

                # 优先级1：过滤词检查
                contains_filter_word = any(
                    filter_word.lower() in title_lower for filter_word in filter_words
                )
                if contains_filter_word:
                    continue

                # 兼容数据格式
                if isinstance(title_data, dict):
                    source_ranks = title_data.get("ranks", [])
                    source_url = title_data.get("url", "")
                    source_mobile_url = title_data.get("mobileUrl", "")
                else:
                    source_ranks = title_data if isinstance(title_data, list) else []
                    source_url = ""
                    source_mobile_url = ""

                # 检查每个词组
                for group in word_groups:
                    group_key = group['group_key']
                    required_words = group['required']
                    normal_words = group['normal']

                    # 优先级2：必须词检查
                    if required_words:
                        all_required_present = all(
                            req_word.lower() in title_lower for req_word in required_words
                        )
                        if not all_required_present:
                            continue

                    # 优先级3：频率词检查
                    if normal_words:
                        any_normal_present = any(
                            normal_word.lower() in title_lower for normal_word in normal_words
                        )
                        if not any_normal_present:
                            continue

                    # 如果只有必须词没有频率词，且所有必须词都匹配了，那么也算匹配
                    # 如果既有必须词又有频率词，那么必须词全部匹配且至少一个频率词匹配
                    # 如果只有频率词，那么至少一个频率词匹配

                    # 匹配成功，记录数据
                    word_stats[group_key]["count"] += 1
                    if source_id not in word_stats[group_key]["titles"]:
                        word_stats[group_key]["titles"][source_id] = []

                    # 获取标题详细信息
                    first_time = ""
                    last_time = ""
                    count_info = 1
                    ranks = source_ranks if source_ranks else []
                    url = source_url
                    mobile_url = source_mobile_url

                    if (title_info and source_id in title_info and title in title_info[source_id]):
                        info = title_info[source_id][title]
                        first_time = info.get("first_time", "")
                        last_time = info.get("last_time", "")
                        count_info = info.get("count", 1)
                        if "ranks" in info and info["ranks"]:
                            ranks = info["ranks"]
                        url = info.get("url", source_url)
                        mobile_url = info.get("mobileUrl", source_mobile_url)

                    if not ranks:
                        ranks = [99]

                    time_display = StatisticsCalculator._format_time_display(first_time, last_time)

                    source_alias = id_to_alias.get(source_id, source_id)
                    word_stats[group_key]["titles"][source_id].append({
                        "title": title,
                        "source_alias": source_alias,
                        "first_time": first_time,
                        "last_time": last_time,
                        "time_display": time_display,
                        "count": count_info,
                        "ranks": ranks,
                        "rank_threshold": rank_threshold,
                        "url": url,
                        "mobileUrl": mobile_url,
                    })

                    # 标记已处理
                    if source_id not in processed_titles:
                        processed_titles[source_id] = {}
                    processed_titles[source_id][title] = True
                    break  # 只匹配第一个词组

        # 转换统计结果
        stats = []
        for group_key, data in word_stats.items():
            all_titles = []
            for source_id, title_list in data["titles"].items():
                all_titles.extend(title_list)

            stats.append({
                "word": group_key,
                "count": data["count"],
                "titles": all_titles,
                "percentage": (
                    round(data["count"] / total_titles * 100, 2)
                    if total_titles > 0 else 0
                ),
            })

        stats.sort(key=lambda x: x["count"], reverse=True)
        return stats, total_titles

    @staticmethod
    def _format_rank_for_html(ranks: List[int], rank_threshold: int = 5) -> str:
        """格式化HTML排名显示"""
        if not ranks:
            return ""

        unique_ranks = sorted(set(ranks))
        min_rank = unique_ranks[0]
        max_rank = unique_ranks[-1]

        if min_rank <= rank_threshold:
            if min_rank == max_rank:
                return f"<font color='red'><strong>[{min_rank}]</strong></font>"
            else:
                return f"<font color='red'><strong>[{min_rank} - {max_rank}]</strong></font>"
        else:
            if min_rank == max_rank:
                return f"[{min_rank}]"
            else:
                return f"[{min_rank} - {max_rank}]"

    @staticmethod
    def _format_rank_for_feishu(ranks: List[int], rank_threshold: int = 5) -> str:
        """格式化飞书排名显示"""
        if not ranks:
            return ""

        unique_ranks = sorted(set(ranks))
        min_rank = unique_ranks[0]
        max_rank = unique_ranks[-1]

        if min_rank <= rank_threshold:
            if min_rank == max_rank:
                return f"<font color='red'>**[{min_rank}]**</font>"
            else:
                return f"<font color='red'>**[{min_rank} - {max_rank}]**</font>"
        else:
            if min_rank == max_rank:
                return f"[{min_rank}]"
            else:
                return f"[{min_rank} - {max_rank}]"

    @staticmethod
    def _format_time_display(first_time: str, last_time: str) -> str:
        """格式化时间显示"""
        if not first_time:
            return ""

        if first_time == last_time or not last_time:
            return first_time
        else:
            return f"[{first_time} ~ {last_time}]"


class ReportGenerator:
    """报告生成器"""

    @staticmethod
    def generate_html_report(
        stats: List[Dict],
        total_titles: int,
        failed_ids: Optional[List] = None,
        is_daily: bool = False,
    ) -> str:
        """生成HTML报告"""
        if is_daily:
            filename = "当日统计.html"
        else:
            filename = f"{TimeHelper.format_time_filename()}.html"

        file_path = FileHelper.get_output_path("html", filename)

        html_content = ReportGenerator._create_html_content(
            stats, total_titles, failed_ids, is_daily
        )

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        # 当日统计同时生成根目录index.html
        if is_daily:
            root_file_path = Path("index.html")
            with open(root_file_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            print(f"当日统计报告已保存到根目录: {root_file_path.resolve()}")

        return file_path

    @staticmethod
    def _create_html_content(
        stats: List[Dict],
        total_titles: int,
        failed_ids: Optional[List] = None,
        is_daily: bool = False,
    ) -> str:
        """创建HTML内容"""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>频率词统计报告</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 20px; }
                h1, h2 { color: #333; }
                table { border-collapse: collapse; width: 100%; margin-top: 20px; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                tr:nth-child(even) { background-color: #f9f9f9; }
                .word { font-weight: bold; }
                .count { text-align: center; }
                .percentage { text-align: center; }
                .titles { max-width: 500px; }
                .source { color: #666; font-style: italic; }
                .error { color: #d9534f; }
                .news-link { 
                    color: #007bff; 
                    text-decoration: none; 
                    border-bottom: 1px dotted #007bff;
                }
                .news-link:hover { 
                    color: #0056b3; 
                    text-decoration: underline; 
                }
                .news-link:visited { 
                    color: #6f42c1; 
                }
                .no-link { 
                    color: #333; 
                }
            </style>
        </head>
        <body>
            <h1>频率词统计报告</h1>
        """

        if is_daily:
            html += "<p>报告类型: 当日汇总</p>"

        now = TimeHelper.get_beijing_time()
        html += f"<p>总标题数: {total_titles}</p>"
        html += f"<p>生成时间: {now.strftime('%Y-%m-%d %H:%M:%S')}</p>"

        # 失败信息
        if failed_ids and len(failed_ids) > 0:
            html += """
            <div class="error">
                <h2>请求失败的平台</h2>
                <ul>
            """
            for id_value in failed_ids:
                html += f"<li>{ReportGenerator._html_escape(id_value)}</li>"
            html += """
                </ul>
            </div>
            """

        html += """
            <table>
                <tr>
                    <th>排名</th>
                    <th>频率词</th>
                    <th>出现次数</th>
                    <th>占比</th>
                    <th>相关标题</th>
                </tr>
        """

        # 表格内容
        for i, stat in enumerate(stats, 1):
            formatted_titles = []
            for title_data in stat["titles"]:
                title = title_data["title"]
                source_alias = title_data["source_alias"]
                time_display = title_data["time_display"]
                count_info = title_data["count"]
                ranks = title_data["ranks"]
                rank_threshold = title_data["rank_threshold"]
                url = title_data.get("url", "")
                mobile_url = title_data.get("mobileUrl", "")

                rank_display = StatisticsCalculator._format_rank_for_html(ranks, rank_threshold)

                link_url = mobile_url or url
                escaped_title = ReportGenerator._html_escape(title)
                escaped_source_alias = ReportGenerator._html_escape(source_alias)
            
                if link_url:
                    escaped_url = ReportGenerator._html_escape(link_url)
                    formatted_title = f"[{escaped_source_alias}] <a href=\"{escaped_url}\" target=\"_blank\" class=\"news-link\">{escaped_title}</a>"
                else:
                    formatted_title = f"[{escaped_source_alias}] <span class=\"no-link\">{escaped_title}</span>"
            
                if rank_display:
                    formatted_title += f" {rank_display}"
                if time_display:
                    escaped_time_display = ReportGenerator._html_escape(time_display)
                    formatted_title += f" <font color='grey'>- {escaped_time_display}</font>"
                if count_info > 1:
                    formatted_title += f" <font color='green'>({count_info}次)</font>"

                formatted_titles.append(formatted_title)

            escaped_word = ReportGenerator._html_escape(stat['word'])
            html += f"""
                <tr>
                    <td>{i}</td>
                    <td class="word">{escaped_word}</td>
                    <td class="count">{stat['count']}</td>
                    <td class="percentage">{stat['percentage']}%</td>
                    <td class="titles">{"<br>".join(formatted_titles)}</td>
                </tr>
            """

        html += """
            </table>
        </body>
        </html>
        """

        return html

    @staticmethod
    def _html_escape(text: str) -> str:
        """HTML转义"""
        if not isinstance(text, str):
            text = str(text)
    
        return (text.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#x27;"))

    @staticmethod
    def send_to_feishu(
        stats: List[Dict],
        failed_ids: Optional[List] = None,
        report_type: str = "单次爬取",
    ) -> bool:
        """发送数据到飞书"""
        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])

        if not webhook_url:
            print(f"警告: FEISHU_WEBHOOK_URL未设置，跳过飞书通知")
            return False

        headers = {"Content-Type": "application/json"}
        total_titles = sum(len(stat["titles"]) for stat in stats if stat["count"] > 0)
        text_content = ReportGenerator._build_feishu_content(stats, failed_ids)

        now = TimeHelper.get_beijing_time()
        payload = {
            "msg_type": "text",
            "content": {
                "total_titles": total_titles,
                "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
                "report_type": report_type,
                "text": text_content,
            },
        }

        try:
            response = requests.post(webhook_url, headers=headers, json=payload)
            if response.status_code == 200:
                print(f"数据发送到飞书成功 [{report_type}]")
                return True
            else:
                print(f"发送到飞书失败 [{report_type}]，状态码：{response.status_code}，响应：{response.text}")
                return False
        except Exception as e:
            print(f"发送到飞书时出错 [{report_type}]：{e}")
            return False

    @staticmethod
    def _build_feishu_content(stats: List[Dict], failed_ids: Optional[List] = None) -> str:
        """构建飞书消息内容"""
        text_content = ""
        filtered_stats = [stat for stat in stats if stat["count"] > 0]

        if filtered_stats:
            text_content += "📊 **热点词汇统计**\n\n"

        total_count = len(filtered_stats)

        for i, stat in enumerate(filtered_stats):
            word = stat["word"]
            count = stat["count"]

            sequence_display = f"<font color='grey'>[{i + 1}/{total_count}]</font>"

            # 频次颜色分级
            if count >= 10:
                text_content += f"🔥 {sequence_display} **{word}** : <font color='red'>{count}</font> 条\n\n"
            elif count >= 5:
                text_content += f"📈 {sequence_display} **{word}** : <font color='orange'>{count}</font> 条\n\n"
            else:
                text_content += f"📌 {sequence_display} **{word}** : {count} 条\n\n"

            # 标题列表
            for j, title_data in enumerate(stat["titles"], 1):
                title = title_data["title"]
                source_alias = title_data["source_alias"]
                time_display = title_data["time_display"]
                count_info = title_data["count"]
                ranks = title_data["ranks"]
                rank_threshold = title_data["rank_threshold"]
                url = title_data.get("url", "")
                mobile_url = title_data.get("mobileUrl", "")

                rank_display = StatisticsCalculator._format_rank_for_feishu(ranks, rank_threshold)

                link_url = mobile_url or url
                if link_url:
                    formatted_title = f"[{title}]({link_url})"
                else:
                    formatted_title = title

                text_content += f"  {j}. <font color='grey'>[{source_alias}]</font> {formatted_title}"
            
                if rank_display:
                    text_content += f" {rank_display}"
                if time_display:
                    text_content += f" <font color='grey'>- {time_display}</font>"
                if count_info > 1:
                    text_content += f" <font color='green'>({count_info}次)</font>"
                text_content += "\n"

                if j < len(stat["titles"]):
                    text_content += "\n"

            # 分割线
            if i < len(filtered_stats) - 1:
                text_content += f"\n{CONFIG['FEISHU_SEPARATOR']}\n\n"

        if not text_content:
            text_content = "📭 暂无匹配的热点词汇\n\n"

        # 失败平台信息
        if failed_ids and len(failed_ids) > 0:
            if text_content and "暂无匹配" not in text_content:
                text_content += f"\n{CONFIG['FEISHU_SEPARATOR']}\n\n"

            text_content += "⚠️ **数据获取失败的平台：**\n\n"
            for i, id_value in enumerate(failed_ids, 1):
                text_content += f"  • <font color='red'>{id_value}</font>\n"

        now = TimeHelper.get_beijing_time()
        text_content += f"\n\n<font color='grey'>更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}</font>"

        return text_content


class NewsAnalyzer:
    """新闻分析器"""

    def __init__(
        self,
        request_interval: int = CONFIG["REQUEST_INTERVAL"],
        feishu_report_type: str = CONFIG["FEISHU_REPORT_TYPE"],
        rank_threshold: int = CONFIG["RANK_THRESHOLD"],
    ):
        """初始化分析器"""
        self.request_interval = request_interval
        self.feishu_report_type = feishu_report_type
        self.rank_threshold = rank_threshold

        self.is_github_actions = os.environ.get("GITHUB_ACTIONS") == "true"

        # 设置代理
        self.proxy_url = None
        if not self.is_github_actions and CONFIG["USE_PROXY"]:
            self.proxy_url = CONFIG["DEFAULT_PROXY"]
            print("本地环境，使用代理")
        elif not self.is_github_actions and not CONFIG["USE_PROXY"]:
            print("本地环境，未启用代理")
        else:
            print("GitHub Actions环境，不使用代理")

        self.data_fetcher = DataFetcher(self.proxy_url)

    def generate_daily_summary(self) -> Optional[str]:
        """生成当日统计报告"""
        print("开始生成当日统计报告...")

        all_results, id_to_alias, title_info = DataProcessor.read_all_today_titles()

        if not all_results:
            print("没有找到当天的数据")
            return None

        total_titles = sum(len(titles) for titles in all_results.values())
        print(f"读取到 {total_titles} 个标题")

        word_groups, filter_words = DataProcessor.load_frequency_words()

        stats, total_titles = StatisticsCalculator.count_word_frequency(
            all_results, word_groups, filter_words,
            id_to_alias, title_info, self.rank_threshold,
        )

        html_file = ReportGenerator.generate_html_report(
            stats, total_titles, is_daily=True
        )
        print(f"当日HTML统计报告已生成: {html_file}")

        if self.feishu_report_type in ["daily", "both"]:
            ReportGenerator.send_to_feishu(stats, [], "当日汇总")

        return html_file

    def run(self) -> None:
        """执行分析流程"""
        now = TimeHelper.get_beijing_time()
        print(f"当前北京时间: {now.strftime('%Y-%m-%d %H:%M:%S')}")

        webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", CONFIG["FEISHU_WEBHOOK_URL"])
        if not webhook_url and not CONFIG["CONTINUE_WITHOUT_FEISHU"]:
            print("错误: FEISHU_WEBHOOK_URL未设置且CONTINUE_WITHOUT_FEISHU为False，程序退出")
            return

        if not webhook_url:
            print("警告: FEISHU_WEBHOOK_URL未设置，将继续执行爬虫但不发送飞书通知")

        print(f"飞书报告类型: {self.feishu_report_type}")
        print(f"排名阈值: {self.rank_threshold}")

        # 爬取目标列表
        ids = [
            ("smzdm", "什么值得买"),
            ("chongbuluo", "虫部落"),
            ("nowcoder", "少数派"),
            ("ithome", "IT之家"),
            ("bilibili-hot-search", "bilibili 热搜"),
            ("v2ex", "v2ex"),
            ("github", "Github"),
            ("linuxdo","linuxdo"),
            ("zhihu","知乎"),
            ("weibo","微博"),
            ("tieba","贴吧"),
            ("douyin","抖音"),
            ("kuaishou","快手"),
            ("pcbeta","论坛"),
        ]

        print(f"开始爬取数据，请求间隔 {self.request_interval} 毫秒")

        FileHelper.ensure_directory_exists("output")

        # 爬取数据
        results, id_to_alias, failed_ids = self.data_fetcher.crawl_websites(ids, self.request_interval)

        # 保存文件
        title_file = DataProcessor.save_titles_to_file(results, id_to_alias, failed_ids)
        print(f"标题已保存到: {title_file}")

        time_info = Path(title_file).stem

        # 创建标题信息
        title_info = {}
        for source_id, titles_data in results.items():
            title_info[source_id] = {}
            for title, title_data in titles_data.items():
                if isinstance(title_data, dict):
                    ranks = title_data.get("ranks", [])
                    url = title_data.get("url", "")
                    mobile_url = title_data.get("mobileUrl", "")
                else:
                    ranks = title_data if isinstance(title_data, list) else []
                    url = ""
                    mobile_url = ""

                title_info[source_id][title] = {
                    "first_time": time_info,
                    "last_time": time_info,
                    "count": 1,
                    "ranks": ranks,
                    "url": url,
                    "mobileUrl": mobile_url,
                }

        word_groups, filter_words = DataProcessor.load_frequency_words()

        stats, total_titles = StatisticsCalculator.count_word_frequency(
            results, word_groups, filter_words,
            id_to_alias, title_info, self.rank_threshold,
        )

        # 发送报告
        if self.feishu_report_type in ["current", "both"]:
            ReportGenerator.send_to_feishu(stats, failed_ids, "单次爬取")

        html_file = ReportGenerator.generate_html_report(stats, total_titles, failed_ids)
        print(f"HTML报告已生成: {html_file}")

        daily_html = self.generate_daily_summary()

        # 本地环境自动打开HTML
        if not self.is_github_actions and html_file:
            file_url = "file://" + str(Path(html_file).resolve())
            print(f"正在打开HTML报告: {file_url}")
            webbrowser.open(file_url)

            if daily_html:
                daily_url = "file://" + str(Path(daily_html).resolve())
                print(f"正在打开当日统计报告: {daily_url}")
                webbrowser.open(daily_url)


def main():
    """程序入口"""
    analyzer = NewsAnalyzer(
        request_interval=CONFIG["REQUEST_INTERVAL"],
        feishu_report_type=CONFIG["FEISHU_REPORT_TYPE"],
        rank_threshold=CONFIG["RANK_THRESHOLD"],
    )
    analyzer.run()


if __name__ == "__main__":
    main()
