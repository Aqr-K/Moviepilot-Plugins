import base64
import ipaddress
import threading
from datetime import datetime, timedelta
from typing import Any, List, Dict, Tuple, Optional

import pytz
from requests import Response
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase
from app.schemas.types import NotificationType
from app.utils.http import RequestUtils
from app.utils.system import SystemUtils
from app.utils.url import UrlUtils

lock = threading.Lock()


class RouterOSDNS(_PluginBase):
    # 插件名称
    plugin_name = "ROS软路由DNS Static"
    # 插件描述
    plugin_desc = "定时将本地Hosts同步至 RouterOS 的 DNS Static 中。"
    # 插件版本
    plugin_version = "0.4"
    # 插件作者
    plugin_author = "Aqr-K"
    # 插件图标
    plugin_icon = "https://raw.githubusercontent.com/Aqr-K/MoviePilot-Plugins/main/icons/Routeros_A.png"
    # 作者主页
    author_url = "https://github.com/Aqr-K"
    # 插件配置项ID前缀
    plugin_config_prefix = "routerosdns_"
    # 加载顺序
    plugin_order = 63
    # 可使用的用户级别
    auth_level = 1

    # 是否开启
    _enabled: bool = False
    # 立即运行一次
    _onlyonce: bool = False
    # 同步清除记录
    _disabled_del: bool = False
    # 发送通知
    _notify: bool = False
    # 发送通知类型
    _msg_type = "Plugin"
    # 任务执行间隔
    _cron: str = "0 6 * * *"
    # 路由器地址
    _address: str = None
    # 超时时间
    _timeout: int = 10
    # TTL
    _ttl: int = 86400
    # 管理员账号
    _username: str = None
    # 管理员密码
    _password: str = None
    # IPv4
    _ipv4: bool = True
    # IPv6
    _ipv6: bool = True
    # 忽略的IP或域名
    _ignore: str = None

    # 定时器
    _scheduler = None
    # 退出事件
    _event = threading.Event()

    def init_plugin(self, config: dict = None):
        if not config:
            return

        self._enabled = config.get("enabled", False)
        self._onlyonce = config.get("onlyonce", False)
        self._disabled_del = config.get("disabled_del", False)
        self._cron = config.get("cron", "0 6 * * *")
        self._notify = config.get("notify")
        self._msg_type = config.get("msg_type")
        self._address = config.get("address")
        self._timeout = config.get("timeout")
        self._ttl = config.get("ttl", 86400)
        self._username = config.get("username")
        self._password = config.get("password")
        self._ipv4 = config.get("ipv4", True)
        self._ipv6 = config.get("ipv6", True)
        self._ignore = config.get("ignore")

        # 停止现有任务
        self.stop_service()

        # 启动服务
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        is_onlyonce = False
        if self._onlyonce:
            logger.info(f"{self.plugin_name}服务，立即运行一次")
            self._scheduler.add_job(
                func=self.add_or_update_remote_dns_from_local_hosts,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=3),
                name=f"{self.plugin_name}",
            )
            # 关闭一次性开关
            self._onlyonce = False
            config["onlyonce"] = False
            self.update_config(config=config)
            is_onlyonce = True

        # 当关闭插件时，同步删除现有的记录，仅enabled生效，onlyonce时，不触发
        if is_onlyonce and self._enabled is False and self._disabled_del:
            self.delete_local_hosts_from_remote_dns()

        # 启动服务
        if self._scheduler.get_jobs():
            self._scheduler.print_jobs()
            self._scheduler.start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled and self._cron:
            logger.info(f"{self.plugin_name}定时服务启动，时间间隔 {self._cron} ")
            return [{
                "id": self.__class__.__name__,
                "name": f"{self.plugin_name}服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.add_or_update_remote_dns_from_local_hosts,
                "kwargs": {}
            }]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            logger.info(str(e))

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.value
            })

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                            'hint': '开启后插件将处于激活状态',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'notify',
                                            'label': '发送通知',
                                            'hint': '是否在特定事件发生时发送通知',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VAutocomplete',
                                        'props': {
                                            'multiple': False,
                                            'model': 'msg_type',
                                            'label': '消息类型',
                                            'placeholder': '自定义消息发送类型',
                                            'items': MsgTypeOptions,
                                            'hint': '选择消息的类型',
                                            'persistent-hint': True,
                                            'active': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立即运行一次',
                                            'hint': '插件将立即运行一次',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'disabled_del',
                                            'label': '同步清除记录',
                                            'hint': '停止创建时，同步清除hosts中命中的DNS记录',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'cron',
                                            'label': '执行周期',
                                            'placeholder': '5位cron表达式',
                                            'hint': '使用cron表达式指定执行周期，如 0 8 * * *',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ipv4',
                                            'label': 'IPv4',
                                            'hint': '同步IPv4地址的Hosts',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'ipv6',
                                            'label': 'IPv6',
                                            'hint': '同步IPv6地址的Hosts',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            },

                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'timeout',
                                            'label': '超时时间',
                                            'placeholder': '请求超时时间，单位秒',
                                            'hint': '设置请求的超时时间',
                                            'persistent-hint': True,
                                            'type': 'number',
                                            'min': 1,
                                            'suffix': '秒',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 8
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'address',
                                            'label': '路由器地址',
                                            'placeholder': '192.168.*.* or http(s)://example.com:443',
                                            'hint': '请输入路由器的地址',
                                            'persistent-hint': True,
                                            'clearable': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ttl',
                                            'label': 'TTL',
                                            'placeholder': 'DNS记录的TTL时间',
                                            'hint': '设置DNS记录的TTL时间，最小120',
                                            'persistent-hint': True,
                                            'type': 'number',
                                            'min': 120,
                                            'suffix': '秒',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'username',
                                            'label': '管理员',
                                            'placeholder': 'RouterOS的管理员用户，如：admin',
                                            'hint': '请输入管理员账号',
                                            'persistent-hint': True,
                                            'clearable': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 6
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'password',
                                            'label': '密码',
                                            'placeholder': 'RouterOS的管理员用户的密码',
                                            'hint': '请输入管理员账号密码',
                                            'persistent-hint': True,
                                            'clearable': True,
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'ignore',
                                            'label': '忽略的IP或域名',
                                            'hint': '请使用|进行分割，如：10.10.10.1|wiki.movie-pilot.org',
                                            'persistent-hint': True,
                                            'clearable': True,
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '注意：可以配合自定义Hosts以及Cloudflare IP优选插件，实现RouterOS路由Cloudflare优选'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "disabled_del": False,
            "cron": "0 6 * * *",
            "notify": True,
            "msg_type": "Plugin",
            "address": None,
            "timeout": 10,
            "ttl": 86400,
            "username": None,
            "password": None,
            "ipv4": True,
            "ipv6": True,
            "ignore": None,
        }

    def get_page(self) -> List[dict]:
        pass

    @staticmethod
    def __correct_the_address_format(url: str) -> Optional[str]:
        """
        校正地址格式
        """
        data = UrlUtils.parse_url_params(url=url)
        if data:
            protocol, hostname, port, path = data
            base_url = f"{protocol}://{hostname}:{port}{path}"
            return base_url
        return None

    @property
    def __ros_headers(self) -> dict:
        """
        获取路由器请求头
        """
        if not self._username or not self._password:
            raise ValueError("RouterOS用户名或密码未设置")
        auth = base64.b64encode(f"{self._username}:{self._password}".encode("utf-8")).decode("utf-8")
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        }

    def __get_base_url(self) -> Optional[str]:
        """
        获取基础api
        """
        try:
            if not self._address:
                raise ValueError("RouterOS地址未设置")
            return self.__correct_the_address_format(url=self._address) + "rest/ip/dns/static"
        except Exception as e:
            logger.error(f"获取RouterOS地址失败: {e}")
            return None

    def add_or_update_remote_dns_from_local_hosts(self) -> bool:
        """
        添加/更新 本地hosts内容到远程dns
        """
        # dns 地址
        base_url = self.__get_base_url()
        if not base_url:
            return False
        # 获取远程hosts
        remote_dns_static_list = self.__get_dns_record(url=base_url)
        # 获取本地hosts
        local_hosts_lines = self.__get_local_hosts()
        # 将本地的hosts解析转换成列表字典
        local_hosts_list = self.__get_local_hosts_list(lines=local_hosts_lines)

        if not local_hosts_list:
            self.__send_message(title="【RouterOS路由DNS Static更新】", text="获取本地hosts失败，更新失败，请检查日志")
            return False

        # 获取需要更新/新增的列表
        updated_list, add_list = self.__update_remote_dns_with_local(list(local_hosts_list),
                                                                     list(remote_dns_static_list))

        # 执行 更新/新增
        if not updated_list and not add_list:
            logger.info("没有需要 更新 或 新增 的 DNS 记录")
            return False
        else:
            add_success, update_success, add_error, update_error = 0, 0, 0, 0
            if updated_list:
                for update_dict in updated_list:
                    record_id = update_dict[".id"]
                    record_name = update_dict["name"]
                    try:
                        # 安全更新，避免id被异常更新产生错误
                        record_data = update_dict.pop(".id", None)
                        # 更新单个值
                        success = self.__update_dns_record(url=base_url, record_id=record_id, record=record_data)
                        if success:
                            update_success += 1
                        else:
                            update_error += 1
                    except Exception as e:
                        logger.error(f"更新 {record_name} 失败: {e}")
                        update_error += 1

            if add_list:
                for add_dict in add_list:
                    record_name = add_dict["name"]
                    record_data = add_dict.pop(".id", None)
                    try:
                        success = self.__add_dns_record(url=base_url, record=record_data)
                        if success:
                            add_success += 1
                        else:
                            add_error += 1
                    except Exception as e:
                        logger.error(f"添加 {record_name} 失败: {e}")
                        add_error += 1

            # 开始汇报结果
            text = f"本次同步结果：应新增 {int(add_success) + int(add_error)} 项记录，成功 {int(add_success)} 项，失败 {int(add_error)} 项；应更新 {int(update_success) + int(update_error)}，成功 {int(update_success)}项，失败 {int(update_error)}项。"
            logger.info(text)
            self.__send_message(title="【RouterOS路由DNS Static更新】", text=text)

            return True

    def delete_local_hosts_from_remote_dns(self) -> bool:
        """
        在远程 dns 中同步删除本地 hosts
        """
        # dns 地址
        base_url = self.__get_base_url()
        # 获取远程hosts
        remote_dns_static_list = self.__get_dns_record(url=base_url)
        # 获取本地hosts
        local_hosts_lines = self.__get_local_hosts()
        # 将本地的hosts解析转换成列表字典
        local_hosts_list = self.__get_local_hosts_list(lines=local_hosts_lines)
        if not local_hosts_list:
            self.__send_message(title="【RouterOS路由DNS Static同步删除】", text="获取本地hosts失败，删除失败，请检查日志")
            return False

        if remote_dns_static_list:
            # 判断哪些local在remote中存在，生成delete_list
            delete_list = self.__delete_remote_dns_with_local(local_list=local_hosts_list,
                                                              remote_list=list(remote_dns_static_list))
            if delete_list:
                delete_success, delete_error = 0, 0
                for delete_dict in delete_list:
                    record_id = delete_dict[".id"]
                    record_name = delete_dict["name"]
                    try:
                        success = self.__delete_dns_record(url=base_url, record_id=record_id)
                        if success:
                            delete_success += 1
                        else:
                            delete_error += 1
                    except Exception as e:
                        logger.error(f"同步删除 {record_name} 失败：{e}")
                        delete_error += 1

                text = f"本次删除结果：应删除 {int(delete_success) + int(delete_error)} 项记录，成功 {int(delete_success)} 项，失败 {int(delete_error)} 项。"
                logger.info(text)
                self.__send_message(title="【RouterOS路由DNS Static同步删除】", text=text)
        else:
            logger.warn(f"远程 dns 列表为空，跳过")

        return True

    def __update_remote_dns_with_local(self, local_list: list, remote_list: list) -> Tuple[list, list]:
        """
        结合本地hosts与远程dns 生成新增与更新字典
        """
        update_list = []
        add_list = []
        try:
            ignore = self._ignore.split("|") if self._ignore else []
            ignore.extend(["localhost"])

            for local_dict in local_list:
                local_ip = local_dict.get("ip", None)
                local_addresses = local_dict.get("addresses", [])

                if not local_ip or not local_addresses or local_ip in ignore:
                    continue

                for local_address in local_addresses:
                    if local_address in ignore:
                        continue

                    is_update = False
                    if remote_list:
                        for remote_dict in remote_list:
                            remote_id = remote_dict.get(".id", None)
                            remote_name = remote_dict.get("name", None)

                            # 更新，仅更新匹配到的第一条，避免错误
                            if remote_name == local_address:
                                # 判断本地IP是IPv4还是IPv6
                                not_ignore, ip_version = self.__should_ignore_ip_and_judge_v4_or_v6(ip=local_ip)
                                if not_ignore:
                                    update_list.append(self.__build_record_data(record_address=local_ip,
                                                                                record_id=remote_id,
                                                                                record_name=remote_name,
                                                                                ip_version=ip_version,
                                                                                record_data=remote_dict))

                                    is_update = True
                                    break

                    # 新增
                    if is_update is False:
                        not_ignore, ip_version = self.__should_ignore_ip_and_judge_v4_or_v6(ip=local_ip)
                        if not_ignore:
                            add_list.append(self.__build_record_data(record_address=local_ip,
                                                                     record_name=local_address,
                                                                     ip_version=ip_version))
            return update_list, add_list

        except Exception as e:
            logger.error(f"无法获取需要 新增 或 更新 的 dns 列表：{e}")
            return [], []

    @staticmethod
    def __delete_remote_dns_with_local(local_list: list, remote_list: list) -> list:
        """
        结合本地hosts与远程dns 生成删除字典
        """
        delete_list = []
        try:
            for local_dict in local_list:
                local_addresses = local_dict.get("addresses", [])
                if local_addresses:
                    for local_address in local_addresses:
                        for remote_dict in remote_list:
                            remote_id = remote_dict.get(".id")
                            remote_name = remote_dict.get("name")
                            if remote_name == local_address:
                                delete_list.append({
                                    "id": remote_id,
                                    "name": remote_name,
                                })

            return delete_list
        except Exception as e:
            logger.error(f"无法获取需要 删除 的 dns 列表：{e}")
            return []

    @staticmethod
    def __get_local_hosts() -> list:
        """
        获取本地hosts文件的内容
        """
        try:
            logger.info("正在准备获取本地hosts")
            # 确定hosts文件的路径
            if SystemUtils.is_windows():
                hosts_path = r"c:\windows\system32\drivers\etc\hosts"
            else:
                hosts_path = '/etc/hosts'
            with open(hosts_path, "r", encoding="utf-8") as file:
                local_hosts = file.readlines()
            logger.info(f"本地hosts文件读取成功: {local_hosts}")
            return local_hosts
        except Exception as e:
            logger.error(f"读取本地hosts文件失败: {e}")
            return []

    @staticmethod
    def __get_local_hosts_list(lines) -> list:
        """
        将Hosts解析成列表字典
        :param lines:
        :return:
        """
        results = []
        if not lines:
            return results

        for line in lines:
            # 去除字符串两端的空白字符
            line = line.strip()

            # 处理行内注释：保留井号前的内容
            if '#' in line:
                line = line.split('#', 1)[0].strip()  # 仅保留第一个#前的内容

            # 跳过空行
            if not line:
                continue

            # 按连续空白符分割（兼容空格和制表符）
            line_parts = line.split()

            # 必须同时满足IP和主机名两部分
            if len(line_parts) < 2:
                continue

            # 解构有效部分
            ip, *addresses = line_parts

            # 构建结果字典
            results.append({
                'ip': ip,
                'addresses': addresses,
            })

        return results

    def __should_ignore_ip_and_judge_v4_or_v6(self, ip: str) -> Tuple[bool, Optional[int]]:
        """
        检查是否应该忽略给定的IP地址，并判断是IPv4还是IPv6地址
        """
        try:
            ip_obj = ipaddress.ip_address(ip)
            # 忽略本地回环地址 (127.0.0.0/8)
            if not ip_obj.is_loopback:
                if ip_obj.version == 4 and self._ipv4:
                    return True, 4
                if ip_obj.version == 6 and self._ipv6:
                    return True, 6
        except ValueError:
            pass
        except Exception as e:
            logger.error(f"判断 {ip} 类型错误：{e}")
        return False, None

    def __send_message(self, title: str, text: str):
        """
        发送消息
        """
        if not self._notify:
            return

        self.post_message(mtype=getattr(NotificationType, self._msg_type, NotificationType.Plugin.value),
                          title=title,
                          text=text)

    def __build_record_data(self, record_address: str, record_name: str, ip_version: int,
                            record_disabled: str = None, record_dynamic: str = None, record_match_subdomain: str = None,
                            record_id: str = None, record_data: dict = None) -> dict:
        """
        处理 添加/更新 数据
        """
        if ip_version == 4:
            record_address_type = "A"
        elif ip_version == 6:
            record_address_type = "AAAA"
        else:
            record_address_type = "CNAME"

        if self._ttl < 120:
            self._ttl = 24 * 60 * 60
            self.__update_config()
        # 将 ttl 转换成 d h:m:s 格式
        total_seconds = int(self._ttl)
        days = total_seconds // (24 * 60 * 60)
        remainder = total_seconds % (24 * 60 * 60)
        hours = remainder // (60 * 60)
        remainder %= (60 * 60)
        minutes = remainder // 60
        seconds = remainder % 60

        ttl_str = f"{days}d {hours}h{minutes}m{seconds}s"

        # 在原有数据的基础上进行更新
        if record_data:
            record = record_data
            # 更新数据
            record["disabled"] = record_disabled if record_disabled else record.get("disabled", "false")
            record["dynamic"] = record_dynamic if record_dynamic else record.get("dynamic", "false")
            record["match-subdomain"] = record_match_subdomain if record_match_subdomain else record.get("match-subdomain", "false")
            record["ttl"] = ttl_str
            record["name"] = record_name
            record["type"] = record_address_type
        # 创建新数据
        else:
            record = {
                ".id": record_id,
                "disabled": record_disabled,
                "dynamic": record_dynamic,
                "name": record_name,
                "ttl": ttl_str,
                "type": record_address_type,
            }

        if record_address_type in ["A", "AAAA"]:
            record.update({"address": record_address})
            record.pop("cname", None)
        else:
            record.update({"cname": record_address})
            record.pop("address", None)

        return record

    """
    api 请求方法
    """

    def __request_ros_api(self, method, url: str, data: dict = None) -> Optional[Response] | List:
        """
        通用请求方法，处理RouterOS路由器的DNS Static
        """
        log_tag = "尝试处理"
        try:
            if method == "get":
                log_tag = "获取"
            elif method == "put":
                log_tag = "添加"
            elif method == "patch":
                log_tag = "更新"
            elif method == "delete":
                log_tag = "删除"
            else:
                raise ValueError(f"不支持的请求方法: {method}")

            data = {"json": data} if data else {}

            response = RequestUtils(timeout=self._timeout).request(url=url,
                                                                   method=method,
                                                                   headers=self.__ros_headers,
                                                                   **data)
            if not response:
                logger.warning(f"{log_tag} DNS 记录失败，响应为空")
                return []
            return response

        except Exception as e:
            # 处理其他异常
            logger.error(f"{log_tag} DNS 记录时发生错误: {e}")
            return []

    def __get_dns_record(self, url: str, record_id=None) -> Optional[Response]:
        """
        获取 MikroTik 路由器的 DNS 记录列表。
        """
        if record_id:
            url = f"{url.rstrip('/')}/{record_id}"
        logger.debug(f"开始获取 DNS 记录: {url}")
        response = self.__request_ros_api(url=url, method="get")
        logger.info(f"获取 DNS 记录成功: {response}")
        return response

    def __add_dns_record(self, url: str, record: dict) -> Optional[Response]:
        """
        向 MikroTik 路由器添加 DNS 记录。
        """
        response = self.__request_ros_api(url=url, method="put", data=record)
        return response

    def __update_dns_record(self, url, record_id, record: dict) -> Optional[Response]:
        """
        更新 MikroTik 路由器的 DNS 记录。
        """
        response = self.__request_ros_api(url=f"{url}/{record_id}", method="patch", data=record)
        return response

    def __delete_dns_record(self, url, record_id) -> Optional[Response]:
        """
        从 MikroTik 路由器删除单条 DNS 记录。
        """
        response = self.__request_ros_api(url=f"{url}/{record_id}", method="delete")
        return response

    def __update_config(self):
        """
        更新配置
        """
        config = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "disabled_del": self._disabled_del,
            "cron": self._cron,
            "notify": self._notify,
            "msg_type": self._msg_type,
            "address": self._address,
            "timeout": self._timeout,
            "ttl": self._ttl,
            "username": self._username,
            "password": self._password,
            "ipv4": self._ipv4,
            "ipv6": self._ipv6,
            "ignore": self._ignore
        }
        # 更新配置
        self.update_config(config)
