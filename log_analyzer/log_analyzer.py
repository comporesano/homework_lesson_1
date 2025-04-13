import json
import os
import re
import sys
from datetime import datetime
from statistics import median
from typing import Optional, TextIO, Union

import structlog
from custom_types import ConfigType


class LogAnalyzer:
    """
    Loader for nginx.log files and render reports
    """

    def __init__(
        self,
        report_size: int = 10,
        report_dir: str = "./reports",
        log_dir: str = "./log",
        cache_dir: str = "./cache",
        app_log_dir: str = "./app_log",
        app_log_file: Optional[str] = None,
    ) -> None:
        try:
            # Init config
            self.config: ConfigType = {
                "REPORT_SIZE": report_size,
                "REPORT_DIR": report_dir,
                "LOG_DIR": log_dir,
                "CACHE_DIR": cache_dir,
                "APP_LOG_DIR": app_log_dir,
                "APP_LOG_FILE": app_log_file,
            }
            io_log_file: Optional[TextIO] = None
            # Structlog configuration
            if app_log_file:
                io_log_file = open(file=os.path.join(app_log_dir, app_log_file), mode="a", encoding="utf-8")
            else:
                io_log_file = sys.stdout
            structlog.configure(
                processors=[
                    structlog.processors.add_log_level,
                    structlog.processors.StackInfoRenderer(),
                    structlog.dev.set_exc_info,
                    structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                    structlog.processors.JSONRenderer(),
                ],
                wrapper_class=structlog.BoundLogger,
                context_class=dict,
                logger_factory=structlog.PrintLoggerFactory(file=io_log_file),
                cache_logger_on_first_use=True,
            )
            self.logger = structlog.get_logger()
            self.logger.info(
                "Creating LogAnalyzer instance",
                kwargs={
                    "report_size": report_size,
                    "report_dir": report_dir,
                    "log_dir": log_dir,
                    "cache_dir": cache_dir,
                    "app_log_dir": app_log_dir,
                    "app_log_file": app_log_file,
                },
            )
            if report_size <= 0:
                raise TypeError(f"Attribute report_size - {report_size} invalid")
            # Init parse regex pattern
            self.parse_pattern = r'".+?(?P<url>/[^ ]+).+?(?P<time>\d+\.\d+)$'
            self.logger.info("LogAnalyzer initialized", config=self.config)
        except TypeError as e:
            self.logger.error(
                "Invalid arguments for LogAnalyzer",
                error=str(e),
                kwargs={
                    "report_size": report_size,
                    "report_dir": report_dir,
                    "log_dir": log_dir,
                    "cache_dir": cache_dir,
                    "app_log_dir": app_log_dir,
                    "app_log_file": app_log_file,
                },
            )

    def __check_cache(self, log_file: str, cache_file: str) -> dict | None:
        try:
            edit_date = str(datetime.fromtimestamp(os.path.getmtime(log_file)))
            with open(file=cache_file, mode="r", encoding="utf-8") as cf:
                json_data = json.load(cf)
                cached_edit_date = json_data["mtime"]
            return json_data if edit_date == cached_edit_date else None
        except (FileNotFoundError, json.JSONDecodeError) as e:
            self.logger.warning("Cache check failed", log_file=log_file, error=str(e))
            return None

    def get_result(self) -> dict:
        """
        Get final result
        """
        self.logger.info("Generating report results")
        try:
            raw_data = self.__parse_file()
            requests_data = raw_data.pop("data")
            raw_data["timings_sum"] = 0
            raw_data["data"] = []
            data_dict: dict[str, list] = {}
            for el in requests_data:
                url = el.get("url")
                time = float(el.get("time"))
                raw_data["timings_sum"] += float(time)
                if url not in data_dict:
                    data_dict[url] = []
                data_dict[url].append(time)
            for key in data_dict:
                timings = data_dict[key]
                req_counts = len(timings)
                sum_timings = sum(timings)
                max_time = max(timings)
                median_time = median(timings)
                data_pattern = {
                    "count": req_counts,
                    "count_perc": req_counts / raw_data["requests_count"],
                    "time_sum": sum_timings,
                    "time_perc": sum_timings / raw_data["timings_sum"],
                    "time_avg": sum_timings / req_counts,
                    "time_max": max_time,
                    "time_med": median_time,
                }
                raw_data["data"].append(data_pattern)
            self.logger.info(
                "Report generated successfully",
                url_count=len(raw_data["data"]),
                total_requests=raw_data["requests_count"],
            )
            return raw_data
        except Exception as e:
            self.logger.error("Failed to generate report", error=str(e))
            raise

    def __parse_file(self) -> dict:
        """
        Parse file lines and push it to the dict structure
        """
        self.logger.info("Starting file parsing")
        try:
            file_name = self.__get_last_logfile()
            file_path = os.path.join(self.config["LOG_DIR"], file_name)
            cache_file = os.path.join(self.config["CACHE_DIR"], f"{file_name}.json")
            self.logger.debug("Checking cache", file_path=file_path, cache_file=cache_file)
            if data := self.__check_cache(log_file=file_path, cache_file=cache_file):
                self.logger.info("Using cached data", file_path=file_path)
                return data
            raw_result: dict[str, Union[str, int, list]] = {
                "file_path": file_path,
                "file_name": file_name,
                "requests_count": 0,
                "mtime": str(datetime.fromtimestamp(os.path.getmtime(file_path))),
                "data": [],
            }
            with open(file=file_path, mode="r", encoding="utf-8") as lf:
                for i, line in enumerate(lf):
                    if i == self.config.get("REPORT_SIZE"):
                        with open(file=cache_file, mode="w", encoding="utf-8") as cf:
                            json_data = json.dumps(raw_result)
                            cf.write(json_data)
                        self.logger.info(
                            "File parsing completed with limit",
                            limit=self.config.get("REPORT_SIZE"),
                            parsed_lines=raw_result["requests_count"],
                        )
                        return raw_result
                    raw_result["requests_count"] += 1
                    match = re.search(self.parse_pattern, line)
                    if not match:
                        self.logger.warning("Line didn't match pattern", line_number=i + 1)
                        continue
                    raw_result["data"].append(match.groupdict())
            self.logger.info("File fully parsed", total_lines=raw_result["requests_count"])
            return raw_result
        except Exception as e:
            self.logger.error("File parsing failed", error=str(e))
            raise

    def __get_last_logfile(self) -> str:
        """
        Get last logfile by date
        """
        self.logger.info("Searching for latest log file")
        try:
            log_date_pattern = r"\d{8}"
            res_name = ""
            files = os.listdir(self.config.get("LOG_DIR"))
            if not files:
                self.logger.error("No log files found in directory", directory=self.config.get("LOG_DIR"))
                raise FileNotFoundError("No log files found")
            for i, file_name in enumerate(files):
                file_date = re.search(log_date_pattern, file_name)
                if not file_date:
                    self.logger.warning("File name doesn't contain date", file_name=file_name)
                    continue
                date = datetime.strptime(file_date.group(), "%Y%m%d")
                delta_date = (datetime.now() - date).days
                if i == 0:
                    max_delta = delta_date + 1
                if delta_date < max_delta:
                    max_delta = delta_date
                    res_name = file_name
            if not res_name:
                self.logger.error("No valid log files found")
                raise ValueError("No valid log files found")
            self.logger.info("Latest log file found", file_name=res_name)
            return res_name
        except Exception as e:
            self.logger.error("Failed to find latest log file", error=str(e))
            raise
