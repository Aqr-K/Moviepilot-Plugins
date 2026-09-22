import traceback
from collections import Counter
from datetime import datetime
from threading import Lock
from typing import Any, List, Dict, Tuple, Optional
from collections import OrderedDict

from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import set_key, dotenv_values
from lxml import html

from app.core.config import settings
from app.core.plugin import PluginManager
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.utils.http import RequestUtils

Lock = Lock()


class PluginMarketsAutoUpdate(_PluginBase):
    # 插件名称
    plugin_name = "插件库更新推送"
    # 插件描述
    plugin_desc = "支持从官方Wiki中获取记录的最新全量插件库、结合添加黑名单，自动化添加插件库。"
    # 插件图标
    plugin_icon = "upload.png"
    # 插件版本
    plugin_version = "2.1"
    # 插件作者
    plugin_author = "Aqr-K"
    # 作者主页
    author_url = "https://github.com/Aqr-K"
    # 插件配置项ID前缀
    plugin_config_prefix = "pluginmarketsautoupdate_"
    # 加载顺序
    plugin_order = 29
    # 可使用的用户级别
    auth_level = 1

    env_path = settings.CONFIG_PATH / "app.env"

    pluginmanager = PluginManager()

    # 保存上次获取到的官网数据
    last_wiki_markets_list = []
    # 保存上次黑名单数据
    last_blacklist_markets_list = []

    _enabled = False
    _onlyonce = False
    _corn = 86400
    _enabled_update_notify = False
    _enabled_write_notify = False
    _notify_type = "Plugin"

    settings_level = 0

    _enabled_write_new_markets = False
    _enabled_write_new_markets_to_env = False
    _enabled_blacklist = False
    _blacklist = []

    _enabled_auto_get = False
    _enabled_proxy = True
    _timeout = 5
    _wiki_url = "https://wiki.movie-pilot.org/zh/plugin"
    # 官方 Wiki 曾以 prismjs 代码块记录插件库地址，改版后已变为链接列表，此值仅用于识别历史配置并自动迁移
    LEGACY_WIKI_URL_XPATH = '//pre[@class="prismjs line-numbers" and @v-pre="true"]/code/text()'
    DEFAULT_WIKI_URL_XPATH = '//ul/li/a[starts-with(@href,"https://github.com/")]/@href'
    _wiki_url_xpath = DEFAULT_WIKI_URL_XPATH

    _event = None
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        """
        初始化插件
        """
        logger.info(f"插件 {self.plugin_name} 初始化")
        if not config:
            return False
        else:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._corn = config.get("corn")
            self._enabled_update_notify = config.get("enabled_update_notify")
            self._enabled_write_notify = config.get("enabled_write_notify")
            self._notify_type = config.get("notify_type")

            self._enabled_write_new_markets = config.get("enabled_write_new_markets")
            self._enabled_write_new_markets_to_env = config.get("enabled_write_new_markets_to_env")
            self._enabled_blacklist = config.get("enabled_blacklist")
            self._blacklist = config.get("blacklist")

            self._enabled_auto_get = config.get("enabled_auto_get")
            self._enabled_proxy = config.get("enabled_proxy")
            self._timeout = config.get("timeout")
            self._wiki_url = config.get("wiki_url")
            self._wiki_url_xpath = config.get("wiki_url_xpath")
            # 官方 Wiki 已改版，历史配置中保存的旧 Xpath 永远匹配不到内容，自动迁移到新的默认值
            if self._wiki_url_xpath and self._wiki_url_xpath.strip() == self.LEGACY_WIKI_URL_XPATH:
                self._wiki_url_xpath = self.DEFAULT_WIKI_URL_XPATH
                logger.warning("检测到官方Wiki改版前的旧Xpath配置，已自动迁移为新的默认Xpath")

            last_config = self.get_config(plugin_id="PluginMarketsAutoUpdate")
            self.last_blacklist_markets_list = last_config.get("last_blacklist_markets_list", [])
            self.last_wiki_markets_list = last_config.get("last_wiki_markets_list", [])

            # 当开启写入env，但未开启更新配置时，自动校正
            if self._enabled_write_new_markets_to_env and self._enabled_write_new_markets is False:
                self._enabled_write_new_markets = True
                logger.warning("写入app.env 已启用，更新当前使用配置 未开启，自动开启 更新当前使用配置")
                self.systemmessage.put("写入app.env 已启用，更新当前使用配置 未开启，自动开启 更新当前使用配置")

            # 初始化配置
            self.__update_config()

        if self._onlyonce:
            self.task(manual=True)
        return True

    def get_state(self):
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        """
        try:
            services = []
            if self._enabled and self._corn:
                if isinstance(self._corn, dict):
                    # 提取默认值的value
                    corn = self._corn.get("value")
                elif isinstance(self._corn, str):
                    corn = int(self._corn)
                elif isinstance(self._corn, int | float):
                    corn = int(self._corn)
                else:
                    corn = 86400
                    logger.error(f"无法处理定时时间，默认为每一天运行")

                if self.__is_integer(value=self._corn):
                    # 使用内置间隔时间
                    trigger = "interval"
                    kwargs = {"seconds": int(corn)}
                    logger.debug(f"使用间隔时间运行定时任务 - 【{corn}】")
                else:
                    raise ValueError("corn不是整数，暂不支持其他格式")
                services = [
                    {
                        "id": "PluginMarketUpdate",
                        "name": "定时扫描网页记录的插件库地址",
                        "trigger": trigger,
                        "func": self.task,
                        "kwargs": kwargs
                    }
                ]
            if not services:
                logger.info(f"{self.plugin_name} 插件未启用定时任务")
            return services
        except Exception as e:
            logger.error(f" {self.plugin_name} 插件注册定时认务失败 - {e}")
            return []

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        """
        拼装插件配置页面，需要返回两块数据：1、页面配置；2、数据结构
        """
        default_config = {
            "enabled": False,
            "onlyonce": False,
            "corn": 86400,
            "enabled_update_notify": False,
            "enabled_write_notify": False,
            "notify_type": "Plugin",

            "enabled_write_new_markets": False,
            "enabled_write_new_markets_to_env": False,
            "enabled_blacklist": False,
            "blacklist": [],

            "enabled_auto_get": False,
            "enabled_proxy": True,
            "timeout": 5,
            "wiki_url": "https://wiki.movie-pilot.org/zh/plugin",
            "wiki_url_xpath": self.DEFAULT_WIKI_URL_XPATH,
        }

        # 消息类型
        MsgTypeOptions = []
        for item in NotificationType:
            MsgTypeOptions.append({
                "title": item.value,
                "value": item.name
            })

        corn_options = [
            {'title': '每 1 天', 'value': 86400},
            {'title': '每 2 天', 'value': 172800},
            {'title': '每 3 天', 'value': 259200},
            {'title': '每 4 天', 'value': 345600},
            {'title': '每 5 天', 'value': 432000},
            {'title': '每 6 天', 'value': 518400},
            {'title': '每 7 天', 'value': 604800},
            {'title': '每 15 天', 'value': 1296000},
            {'title': '每 30 天', 'value': 2592000},
            {'title': '每 60 天', 'value': 5184000},
            {'title': '每 90 天', 'value': 7776000},
            {'title': '每 180 天', 'value': 15552000},
            {'title': '每 365 天', 'value': 31536000},
        ]

        markets_list = []

        if self.get_data("data_list"):
            for data in self.get_data("data_list").values():
                markets_list.append({
                    'title': data.get("url"),
                    'value': data.get("url"),
                })
        else:
            # 没有data_list的时候，使用当前使用中的库作为初始化可选菜单
            for plugin_market in self.__valid_markets_list(plugin_markets=settings.PLUGIN_MARKET, mode="当前配置"):
                markets_list.append({
                    'title': plugin_market,
                    'value': plugin_market,
                })

        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'props': {
                            'align': 'center',
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用定时运行',
                                            'hint': '开启后插件处于激活状态，并启用定时任务',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '立刻运行一次',
                                            'hint': '一次性任务；运行后自动关闭',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {

                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'corn',
                                            'label': '定时任务间隔时间',
                                            'hint': '选择定时扫描时间',
                                            'persistent-hint': True,
                                            'active': True,
                                            'items': corn_options,
                                            "item-value": "value",
                                            "item-title": "title",
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'align': 'center',
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled_update_notify',
                                            'label': '发送更新通知',
                                            'hint': '允许发送新库记录通知',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled_write_notify',
                                            'label': '发送写入通知',
                                            'hint': '允许发送新库写入状态通知',
                                            'persistent-hint': True,
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 4,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'notify_type',
                                            'label': '自定义消息通知类型',
                                            'items': MsgTypeOptions,
                                            'hint': '选择推送使用的消息类型',
                                            'persistent-hint': True,
                                            'active': True,
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'props': {
                            'align': 'center',
                        },
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12,
                                    'md': 12,
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'warning',
                                            'variant': 'tonal',
                                            'style': 'white-space: pre-line;',
                                            'text': '注意：\n'
                                                    '直接返回 "查看数据" 并不会触发刷新，只有在保存或关闭后，重新打开插件设置，才能查看刷新后的数据统计。\n'
                                                    '问题反馈：',
                                        },
                                        'content': [
                                            {
                                                'component': 'a',
                                                'props': {
                                                    'href': 'https://github.com/Aqr-K/MoviePilot-Plugins/issues/new',
                                                    'target': '_blank'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'u',
                                                        'text': 'ISSUES（点击跳转）'
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VTabs',
                        'props': {
                            'model': '_tabs',
                            'height': 72,
                            'fixed-tabs': True,
                            'style': {
                                'margin-top': '8px',
                                'margin-bottom': '10px',
                            }
                        },
                        'content': [
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'basic_settings',
                                    'style': {
                                        'padding-top': '10px',
                                        'padding-bottom': '10px',
                                        'font-size': '16px'
                                    },
                                },
                                'text': '基础设置'
                            },
                            {
                                'component': 'VTab',
                                'props': {
                                    'value': 'advanced_settings',
                                    'style': {
                                        'padding-top': '10px',
                                        'padding-bottom': '10px',
                                        'font-size': '16px'
                                    },
                                },
                                'text': '高级设置'
                            },
                        ]
                    },
                    {
                        'component': 'VWindow',
                        'props': {
                            'model': '_tabs',
                        },
                        'content': [
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'basic_settings',
                                    'style': {
                                        'padding-top': '20px',
                                        'padding-bottom': '20px'
                                    },
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enabled_write_new_markets',
                                                            'label': '更新当前使用配置',
                                                            'hint': '出现新插件库时，将更新到当前使用的配置',
                                                            'persistent-hint': True,
                                                        }
                                                    },
                                                ],
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enabled_write_new_markets_to_env',
                                                            'label': '写入app.env',
                                                            'hint': '将更新后的系统配置写入到 app.env 中',
                                                            'persistent-hint': True,
                                                        }
                                                    },
                                                ],
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enabled_blacklist',
                                                            'label': '启用写入黑名单',
                                                            'hint': '黑名单内的插件库不会被写入配置中',
                                                            'persistent-hint': True,
                                                        }
                                                    },
                                                ],
                                            },

                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VCombobox',
                                                        'props': {
                                                            'model': 'blacklist',
                                                            'label': '插件库地址-黑名单',
                                                            'items': markets_list,
                                                            'clearable': True,
                                                            'multiple': True,
                                                            'placeholder': '支持下拉选择，支持手动输入，输入的地址将不会被更新到 系统配置 与 app.env 中',
                                                            'hint': '选中的插件库将被添加到黑名单中，不会自动添加；已写入env的黑名单插件库，也会在下次运行写入时移除；只移除插件库，插件本身不会被卸载',
                                                            'persistent-hint': True,
                                                            'no-data-text': '',
                                                            'active': True,
                                                            'hide-no-data': True,
                                                        }
                                                    }
                                                ]
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VCol',
                                        'props': {
                                            'cols': 12,
                                            'md': 12,
                                        },
                                        'content': [
                                            {
                                                'component': 'VAlert',
                                                'props': {
                                                    'type': 'info',
                                                    'variant': 'tonal',
                                                    'style': 'white-space: pre-line;',
                                                    'text': '基础设置注意事项：\n'
                                                            '1、"更新当前使用配置"：所有平台版本都可使用，重启MP后，当前设置的值会失效，并还原成 app.env 中的原记录值；\n'
                                                            '2、"写入app.env": 将新配置写入到 app.env 中，MP重启时，可正常使用（需要提前映射/config）。\n'
                                                            '\n'
                                                            '补充说明：\n'
                                                            '1、"查看数据"暂无数据时，会读取 当前使用的配置 作为黑名单的可选菜单。\n'
                                                            '2、未启用"写入app.env" 中的值，重启MP后，会恢复到原有 "环境变量" 或 "app.env" 的值；只有等本插件再次运行后才会更新 "系统配置"。\n'
                                                            '3、只启用"写入app.env"的时候，会自动启用"更新当前使用配置"，以保证插件库的正常使用。'
                                                },
                                            }
                                        ]
                                    }
                                ]
                            },
                            {
                                'component': 'VWindowItem',
                                'props': {
                                    'value': 'advanced_settings',
                                    'style': {
                                        'padding-top': '20px',
                                        'padding-bottom': '20px'
                                    },
                                },
                                'content': [
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VSwitch',
                                                        'props': {
                                                            'model': 'enabled_proxy',
                                                            'label': '启用代理访问',
                                                            'hint': '需要配置 PROXY_HOST',
                                                            'persistent-hint': True,
                                                        }
                                                    },
                                                ],
                                            },
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 4,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'timeout',
                                                            'label': '网页访问超时时间',
                                                            'hint': '访问超时时间，最低1秒',
                                                            'suffix': '秒',
                                                            'persistent-hint': True,
                                                            'type': 'number',
                                                            'active': True,
                                                        }
                                                    },
                                                ],
                                            },
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'wiki_url',
                                                            'label': '插件库记录地址',
                                                            'placeholder': 'https://wiki.movie-pilot.org/zh/plugin',
                                                            'hint': '可自定义地址，留空则使用默认地址',
                                                            'persistent-hint': True,
                                                            'active': True,
                                                            'clearable': True,
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VTextField',
                                                        'props': {
                                                            'model': 'wiki_url_xpath',
                                                            'label': '记录页面Xpath定位路径',
                                                            'placeholder': '//pre[@class="prismjs line-numbers" and @v-pre="true"]/code/text()',
                                                            'hint': '提取网页中插件库记录的Xpath路径，留空则使用默认Xpath定位路径',
                                                            'persistent-hint': True,
                                                            'active': True,
                                                            'clearable': True,
                                                        }
                                                    }
                                                ]
                                            }
                                        ]
                                    },
                                    {
                                        'component': 'VRow',
                                        'props': {
                                            'align': 'center',
                                        },
                                        'content': [
                                            {
                                                'component': 'VCol',
                                                'props': {
                                                    'cols': 12,
                                                    'md': 12,
                                                },
                                                'content': [
                                                    {
                                                        'component': 'VAlert',
                                                        'props': {
                                                            'type': 'info',
                                                            'variant': 'tonal',
                                                            'style': 'white-space: pre-line;',
                                                            'text': '高级设置注意事项：\n'
                                                                    '1、当官网出现，域名与路径被替换、Xpath变动时，可自行修改高级设置的 "插件库记录地址"、"记录页面Xpath定位路径"，以保证功能的正常运行。\n\n'
                                                                    '2、启用 "启用代理访问" 需要配置 "PROXY_HOST"；没有配置 "PROXY_HOST" 时，启用该项会默认使用系统网络环境，不会导致运行失败。\n\n'
                                                                    '3、"网页访问超时时间" 只支持整数，单位为秒，小数点后的数字会被后台忽略，如：3.5 会被转换为 3 秒；且在输入的参数存在问题的时候，会自动使用用默认值 5 秒。\n\n'
                                                                    '4、"插件库记录地址"、"记录页面Xpath定位路径" 此两项参数，直接关系到是否能成功获取到网页记录的库地址，不懂得如何获取的用户，请不要随意修改这两项参数！'
                                                        }
                                                    }
                                                ]
                                            }
                                        ],
                                    },
                                ]
                            },
                        ]
                    },
                ]
            },
        ], default_config

    def get_page(self) -> List[dict]:
        """
        拼装插件详情页面，需要返回页面配置，同时附带数据
        """
        data_list = self.get_data("data_list") or {}

        if not data_list:
            return [
                {
                    'component': 'div',
                    'text': '暂无数据',
                    'props': {
                        'class': 'text-center',
                    }
                }
            ]
        else:
            data_list = data_list.values()
            # 按time倒序排序
            data_list = sorted(data_list, key=lambda x: x.get("time") or 0, reverse=True)

        # 表格标题
        headers = [
            {'title': '插件库来源', 'key': 'source', 'sortable': True},
            {'title': '使用状态', 'key': 'status', 'sortable': True},
            {'title': '插件库作者', 'key': 'user', 'sortable': True},
            {'title': '插件库名字', 'key': 'repo', 'sortable': True},
            {'title': '插件库分支', 'key': 'branch', 'sortable': True},
            {'title': '插件库地址', 'key': 'url', 'sortable': True},
        ]

        items = [
            {
                'source': data.get("source"),
                'status': data.get("status"),
                'user': data.get("user"),
                'repo': data.get("repo"),
                'branch': data.get("branch"),
                'url': data.get("url"),
            } for data in data_list
        ]

        return [
            {
                'component': 'VRow',
                'props': {
                    'style': {
                        'overflow': 'hidden',
                    }
                },
                'content':
                    self.__get_total_elements() +
                    [
                        {
                            'component': 'VRow',
                            'props': {
                                'class': 'd-none d-sm-block',
                            },
                            'content': [
                                {
                                    'component': 'VCol',
                                    'props': {
                                        'cols': 12,
                                    },
                                    'content': [
                                        {
                                            'component': 'VDataTableVirtual',
                                            'props': {
                                                'class': 'text-sm',
                                                'headers': headers,
                                                'items': items,
                                                'height': '30rem',
                                                'density': 'compact',
                                                'fixed-header': True,
                                                'hide-no-data': True,
                                                'hover': True
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
            }
        ]

    def stop_service(self):
        """
        退出插件
        """
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.error("退出插件失败：%s" % str(e))

    # init

    def task(self, manual=False):
        """
        启动插件
        """
        with (Lock):
            update_flag, settings_flag, env_flag = False, False, False
            try:
                wiki_markets_list = self.get_wiki_list()
                all_markets_list = self.get_all_markets_list(wiki_markets_list=wiki_markets_list)

                settings_markets_list, full_markets_list, other_markets_list, new_markets_list, \
                    blacklist_markets_list, full_in_blacklist_markets_list, new_in_blacklist_markets_list = \
                    all_markets_list

                update_count = self.get_all_markets_count(all_markets_list=all_markets_list)
                update_flag = self.check_update(wiki_markets_list=wiki_markets_list,
                                                other_markets_list=other_markets_list)
                self.handle_notify(update_flag=update_flag, count=update_count, mode="update")

                if update_flag:
                    if self._enabled_write_new_markets or self._enabled_write_new_markets_to_env:
                        new_markets_list = self.remove_blacklist_markets(full_markets_list=full_markets_list)
                        # 转换为写入字符串
                        new_markets_str = self.__valid_markets_str(plugin_markets=new_markets_list)
                        # 当前使用配置更新
                        if self._enabled_write_new_markets:
                            settings_flag = self.update_settings_markets(markets_str=new_markets_str,
                                                                         new_markets_count=len(new_markets_list))
                            logger.debug(f"当前插件库列表\n{new_markets_list}")
                        # 写入app.env更新
                        if self._enabled_write_new_markets_to_env:
                            env_flag = self.update_env_markets(markets_str=new_markets_str,
                                                               new_markets_count=len(new_markets_list))
                            logger.debug(f"当前插件库列表\n{new_markets_list}")

                        # 通知处理
                        self.handle_notify(settings_flag=settings_flag, env_flag=env_flag, mode="write")
            except Exception as e:
                logger.error(f'{"手动" if manual else "定时"}任务运行失败 - {e}')
                if manual:
                    self._enabled = False
            # 运行成功
            else:
                if update_flag:
                    self.last_wiki_markets_list = wiki_markets_list
                    self.__update_and_save_statistic_info(all_markets_list=all_markets_list,
                                                          wiki_markets_list=wiki_markets_list,
                                                          update_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
                else:
                    # 仅更新时间
                    statistic_info: dict[str, Any] = self.__get_statistic_info()
                    if statistic_info:
                        statistic_info["update_time"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        self.save_data("statistic_info", statistic_info)
                    else:
                        logger.error("未找到统计信息，无法更新时间")

                # 同步显示，只有更新了系统配置插件库，才会同步其他插件的显示
                if settings_flag:
                    logger.info("成功更新系统配置插件库，开始同步其他插件的显示")
                    self.update_other_plugins_settings()
            finally:
                self._onlyonce = False
                self.__update_config()

    """ 处理插件库地址  """

    def get_wiki_list(self):
        """
        获取 Wiki 记录的代码，并转换成 List
        """

        def __get_request_url():
            """
            发送 GET 请求并返回响应对象
            """
            try:
                url = self._wiki_url if self._wiki_url else "https://wiki.movie-pilot.org/zh/plugin"
                result = RequestUtils(proxies=self.__proxies, timeout=self.__timeout()).get_res(url=url)
                if not result:
                    raise ValueError("请求发送失败")
                if result.status_code != 200:
                    raise ValueError(f"请求发送成功，未能返回响应 - {result.status_code}")
                return result
            except Exception as err:
                raise Exception(str(err))

        def __get_code(res_body):
            """
            从 wiki 中提取全量插件库地址
            """
            try:
                tree = html.fromstring(res_body.text)
                code = tree.xpath(self._wiki_url_xpath or self.DEFAULT_WIKI_URL_XPATH)
                if not code:
                    raise ValueError("未找到Xpath路径的值")
                parts = [str(item).strip() for item in code if str(item).strip()]
                # Xpath 命中多个地址节点时（如链接列表）需用逗号分隔，命中单个代码块时行为与此前一致
                separator = "," if all(part.startswith("http") for part in parts) else ""
                code = separator.join(parts)
                logger.debug(f"成功提取到当前网页中记录的插件库地址 - {code}")
                return code
            except Exception as err:
                raise Exception(f"无法从网页中提取全量插件库地址 - {str(err)}")

        try:
            res = __get_request_url()
            wiki_markets_code = __get_code(res_body=res)
            wiki_markets_list = self.__valid_markets_list(plugin_markets=wiki_markets_code, mode="网页记录")
            return wiki_markets_list
        except Exception as e:
            raise Exception(f"获取网页插件库地址记录失败 - {str(e)}")

    def get_blacklist_markets_list(self):
        """
        获取当前使用的黑名单插件库地址
        """
        try:
            if not self._enabled_blacklist:
                logger.warning("未启用黑名单开关，忽略黑名单插件库地址获取")
                return []
            if not self._blacklist:
                logger.warning("黑名单插件库地址为空")
                return []
            blacklist_markets_list = self.__valid_markets_list(plugin_markets=self._blacklist, mode="黑名单插件库")
            return blacklist_markets_list
        except Exception as e:
            raise Exception(f"获取黑名单插件库地址失败 - {str(e)}")

    def check_blacklist_update(self, blacklist_markets_list):
        """
        检查黑名单是否出现更新
        """
        # 上次黑名单记录
        last_blacklist_markets_list = self.__valid_markets_list(plugin_markets=self.last_blacklist_markets_list,
                                                                mode="上次黑名单设置")
        logger.debug(f"上次黑名单：", last_blacklist_markets_list)
        logger.debug(f"这次黑名单：", blacklist_markets_list)
        # 黑名单出现更新，强制判断为需要更新
        if self._enabled_blacklist and set(blacklist_markets_list) != set(last_blacklist_markets_list):
            logger.warning("黑名单插件库与上一次不同，重新判断需要更新的插件库")
            return True
        logger.debug("当前黑名单与上次运行一致")
        return False

    def check_update(self, wiki_markets_list: Optional[list], other_markets_list: Optional[list]):
        """
        检查出现更新
        """
        try:
            # 黑名单状态更新判断
            blacklist_markets_list = self.get_blacklist_markets_list()
            if self.check_blacklist_update(blacklist_markets_list=blacklist_markets_list):
                return True

            # 未启用任何更新方式
            if not self._enabled_write_new_markets and not self._enabled_write_new_markets_to_env:
                logger.info("未启用配置更新，以上次获取到的 官网 插件库缓存进行对比")
                last_wiki_markets_list = self.last_wiki_markets_list
            # 启用任意一项自动更新
            else:
                settings_markets_list = self.__valid_markets_list(plugin_markets=settings.PLUGIN_MARKET, mode="当前配置")
                logger.info("启动配置更新，开始与 当前配置 的插件库进行对比")
                logger.debug(f"当前配置的插件库地址 - {settings_markets_list}")

                # 合并本地插件库与黑名单插件库，再去除第三方插件库，得到最终的插件库地址
                combined_list = list(OrderedDict.fromkeys(settings_markets_list + blacklist_markets_list))
                last_wiki_markets_list = [item for item in combined_list if item not in other_markets_list]

            logger.info(f"官网插件库地址{'未' if set(wiki_markets_list) == set(last_wiki_markets_list) else '发现'}更新")
            return False if set(wiki_markets_list) == set(last_wiki_markets_list) else True
        except Exception as e:
            raise Exception(f"检查出现更新失败 - {str(e)}")

    def get_all_markets_list(self, wiki_markets_list: Optional[list]) -> Tuple[list, ...]:
        """
        获取当前系统配置的插件库地址、当前不在的本地配置中的插件库、当前不在Wiki中的本地配置插件库
        :param wiki_markets_list:
        :return:
        """

        def __get_settings_markets_list() -> list:
            """
            获取当前系统配置的插件库地址 - 使用中的插件库
            """
            try:
                if not settings.PLUGIN_MARKET:
                    logger.warning("当前系统配置的插件库地址为空")
                    return []
                settings_markets = self.__valid_markets_list(plugin_markets=settings.PLUGIN_MARKET, mode="当前配置")
                return settings_markets
            except Exception as err:
                raise Exception(f"获取当前系统配置的插件库地址失败 - {str(err)}")

        def __get_other_settings_markets_list() -> list:
            """
            获取当前不在Wiki中的本地配置插件库 - 未记录的第三方插件库
            """
            try:
                other_markets = [item for item in settings_markets_list if item not in wiki_markets_list]
                return other_markets if other_markets else []
            except Exception as err:
                raise Exception(f"获取当前使用的不在网页记录的插件库中的第三方插件库失败 - {str(err)}")

        def __get_full_markets_list() -> list:
            """
            组合获取全量插件库
            """
            try:
                full_markets = list(OrderedDict.fromkeys(wiki_markets_list + other_markets_list))
                return full_markets if full_markets else []
            except Exception as err:
                raise Exception(f"组合获取全量插件库失败 - {str(err)}")

        def __get_new_markets_list() -> list:
            """
            获取本次发现的新插件库地址
            :return:
            """
            try:
                new_markets = [url for url in full_markets_list if url not in last_wiki_markets_list]
                return new_markets if new_markets else []
            except Exception as err:
                raise Exception(f"获取本次发现的新插件库地址失败 - {str(err)}")

        def __get_new_in_blacklist_markets_list() -> list:
            """
            获取新插件库中在黑名单中的数量
            """
            try:
                in_blacklist_markets = [url for url in new_markets_list if url in blacklist_markets_list]
                return in_blacklist_markets if in_blacklist_markets else []
            except Exception as err:
                raise Exception(f"判断新更新的插件库中是否存在黑名单中的数量失败 - {str(err)}")

        def __get_full_in_blacklist_markets_list() -> list:
            """
            获取全量插件库中在黑名单中的数量
            """
            try:
                full_in_blacklist_markets = [url for url in full_markets_list if url in blacklist_markets_list]
                return full_in_blacklist_markets if full_in_blacklist_markets else []
            except Exception as err:
                raise Exception(f"判断全量插件库中是否存在黑名单中的数量失败 - {str(err)}")

        try:
            wiki_markets_list = wiki_markets_list if wiki_markets_list else []

            blacklist_markets_list = self.get_blacklist_markets_list()
            # Todo：需要重新处理
            last_wiki_markets_list = self.last_wiki_markets_list
            settings_markets_list = __get_settings_markets_list()
            other_markets_list = __get_other_settings_markets_list()
            full_markets_list = __get_full_markets_list()
            new_markets_list = __get_new_markets_list()
            new_in_blacklist_markets_list = __get_new_in_blacklist_markets_list()
            full_in_blacklist_markets_list = __get_full_in_blacklist_markets_list()

            return (settings_markets_list, full_markets_list, other_markets_list, new_markets_list,
                    blacklist_markets_list, full_in_blacklist_markets_list, new_in_blacklist_markets_list)
        except Exception as e:
            raise Exception(f"提取配置失败 - {str(e)}")

    def get_all_markets_count(self, all_markets_list: Tuple) -> Tuple:
        """
        获取新插件库数量
        """
        try:
            settings_markets_list, full_markets_list, other_markets_list, new_markets_list, blacklist_markets_list, \
                full_in_blacklist_markets_list, new_in_blacklist_markets_list = all_markets_list

            if not self._enabled_write_new_markets and not self._enabled_write_new_markets_to_env:
                last_markets_list = self.last_wiki_markets_list
            else:
                last_markets_list = self.__valid_markets_list(plugin_markets=settings.PLUGIN_MARKET, mode="当前配置")

            new_markets_list = [url for url in full_markets_list if
                                url not in (last_markets_list or blacklist_markets_list)]

            settings_count = len(settings_markets_list)
            new_count = len(new_markets_list)
            # 避免负数
            if new_count < 0:
                new_count = 0
            other_count = len(other_markets_list)
            blacklist_count = len(blacklist_markets_list)
            full_in_blacklist_count = len(full_in_blacklist_markets_list)
            new_in_blacklist_count = len(new_in_blacklist_markets_list)

            # 使用中，新插件库，第三方，黑名单插件库，新插件库中在黑名单中的数量
            return (settings_count, new_count, other_count, blacklist_count,
                    full_in_blacklist_count, new_in_blacklist_count)
        except Exception as e:
            raise Exception(f"获取新插件库数量失败 - {str(e)}")

    def remove_blacklist_markets(self, full_markets_list: Optional[list]):
        """
        去除黑名单插件库列表
        """
        try:
            if self._enabled_blacklist:
                blacklist_markets_list = self.get_blacklist_markets_list()
                # 从全量插件库中去除黑名单插件库
                write_markets_list = [url for url in full_markets_list if url not in blacklist_markets_list]
                return write_markets_list
            return full_markets_list
        except Exception as e:
            raise Exception(f"黑名单插件库排除失败 - {e}")

    def get_env_markets_list(self):
        """
        获取当前环境变量中的插件库地址
        """
        try:
            env_markets_str = dotenv_values(self.env_path).get("PLUGIN_MARKET", "")
            env_markets_list = self.__valid_markets_list(plugin_markets=env_markets_str, mode="app.env配置")
            return env_markets_list
        except Exception as e:
            raise Exception(f"获取当前环境变量中的插件库地址失败 - {str(e)}")

    """ 更新 """

    @staticmethod
    def update_settings_markets(markets_str: str, new_markets_count: int):
        """
        更新配置
        """
        try:
            settings.PLUGIN_MARKET = markets_str
            logger.info(f"成功更新系统配置插件库，当前插件库数量 - {new_markets_count}")
            return True
        except Exception as e:
            logger.error(f"更新配置失败 - {str(e)}")
            return False

    def update_env_markets(self, markets_str: str, new_markets_count: int):
        """
        更新env
        """
        try:
            set_key(dotenv_path=self.env_path, key_to_set="PLUGIN_MARKET", value_to_set=markets_str)
            logger.info(f"成功写入app.env插件库，当前插件库数量 - {new_markets_count}")
            return True
        except Exception as e:
            logger.error(f"更新env失败 - {str(e)}")
            return False

    """ 数据处理 """

    @property
    def __proxies(self):
        """
        代理设置
        """
        return None if settings.GITHUB_PROXY and self._enabled_proxy else settings.PROXY

    def __timeout(self) -> int:
        """
        超时设置
        """
        try:
            if self._timeout:
                if isinstance(self._timeout, int):
                    timeout = self._timeout
                elif isinstance(self._timeout, float):
                    timeout = int(self._timeout)
                elif isinstance(self._timeout, str):
                    if self.__is_integer(self._timeout):
                        timeout = int(self._timeout)
                    else:
                        raise ValueError("超时时间格式不合法")
                else:
                    raise ValueError("超时时间格式不合法")
                if 1 > int(timeout) >= 0:
                    raise ValueError("超时时间设置不合法，最小为1秒")
                elif int(timeout) < 0:
                    raise ValueError("超时时间设置不合法，不能为负数")
                return int(timeout)
            else:
                raise ValueError("未设置超时时间")
        except Exception as e:
            self._timeout = 5
            self.__update_config()
            logger.error(f"超时时间设置失败，还原并使用默认值 {int(self._timeout)} 秒 - {e}")
            return int(self._timeout)

    @staticmethod
    def __is_integer(value) -> bool:
        """
        检查字符串是否可以转换为整数
        """
        try:
            if isinstance(value, int):
                return True
            elif isinstance(value, str):
                int(value)
                return True
            elif isinstance(value, float):
                int(value)
                return True
            else:
                return False
        except ValueError:
            return False

    @staticmethod
    def __valid_markets_list(plugin_markets, mode: str = "参数") -> List[str]:
        """
        数据格式化 - 转换为list
        """

        def extract_values(markets):
            if isinstance(markets, str):
                return [url.strip() for url in markets.split(",")]

            elif isinstance(markets, dict):
                return [v.strip() for k, v in markets.items() if k == 'value' and isinstance(v, str)]

            # 递归处理列表中的每个元素
            elif isinstance(markets, list):
                result = []
                for item in markets:
                    result.extend(extract_values(item))
                return result

            else:
                raise ValueError('格式不合法')

        try:
            if plugin_markets:
                plugin_markets_list = extract_values(markets=plugin_markets)
                # 修正输出，以"/"结尾
                return [url if url.endswith("/") else f"{url}/" for url in plugin_markets_list]
            else:
                return []
        except Exception as e:
            raise Exception(f"在 【{mode}】 中执行 list 数据校验与转化失败 - {e}")

    @staticmethod
    def __valid_markets_str(plugin_markets, mode: str = "参数") -> str:
        """
        数据格式化 - 转换为str
        """
        try:
            plugin_markets_str = ""
            if plugin_markets:
                if isinstance(plugin_markets, str):
                    plugin_markets_str = plugin_markets
                elif isinstance(plugin_markets, list):
                    plugin_markets_str = ",".join(plugin_markets)
                elif isinstance(plugin_markets, dict):
                    plugin_markets_str = ",".join(list(plugin_markets.values()))
                else:
                    raise ValueError(f'格式不合法')
            return plugin_markets_str if plugin_markets_str else ""
        except Exception as e:
            raise Exception(f"在 【{mode}】 中执行 str 数据校验与转化失败 - {e}")

    """ 显示同步 """

    def update_other_plugins_settings(self):
        """
        更新其他插件的配置
        """

        def __check_settings_plugins_installed() -> (bool, list):
            """
            检查需要同步的插件是否已安装
            """
            plugin_names = {
                "ConfigCenter": "配置中心",
            }

            # 获取本地插件列表
            local_plugins = self.pluginmanager.get_local_plugins()
            # 初始化已安装插件列表
            installed_plugins_list = []
            # 校验所有的插件是否已安装
            for p_id, p_name in plugin_names.items():
                plugin = next((p for p in local_plugins if p.id == p_id and p.installed), None)
                if plugin:
                    installed_plugins_list.append({p_id: p_name})
            if installed_plugins_list:
                return True, installed_plugins_list
            return False, []

        try:
            write_markets_str = settings.PLUGIN_MARKET
            flag, installed_plugins = __check_settings_plugins_installed()
            if flag:
                logger.debug("正在准备检查同步更新显示")
                for plugin_id, plugin_name in (item for plugin in installed_plugins for item in plugin.items()):
                    config = self.get_config(plugin_id=plugin_id) or {}
                    plugin_market = config.get("PLUGIN_MARKET", "")
                    # 只有在内容变更时，才更新配置
                    if Counter(write_markets_str.split(",")) != Counter(plugin_market.split(",")):
                        config["PLUGIN_MARKET"] = write_markets_str
                        self.update_config(config=config, plugin_id=plugin_id)
                        logger.debug(f"【{plugin_name}】检查完成")
                    else:
                        logger.debug(f"【{plugin_name}】中的值与当前系统配置一致，无需更新")
                logger.info("同步显示检查与更新完成")
        except Exception as e:
            logger.error(f"同步显示检查与更新失败 - {e}")

    """ 推送通知 """

    def handle_notify(self, mode: str, update_flag: bool = False, settings_flag: bool = False, env_flag: bool = False,
                      count: Optional[Tuple] = None):
        """
        处理通知
        """

        def __send_message(title: str, text: str):
            """
            推送消息通知
            """
            mtype = NotificationType.Plugin if not self._notify_type else self._notify_type
            self.post_message(mtype=getattr(NotificationType, mtype, NotificationType.Plugin.value),
                              title=title,
                              text=text)

        try:
            if mode == "update" and self._enabled_update_notify:
                if update_flag:
                    msg = (f"检查到网页记录的插件库地址有更新。\n"
                           f"当前使用了 {count[0]} 个插件库，"
                           f"其中有 {count[2]} 个第三方插件库；\n"
                           f"新发现 {count[1]} 个新插件库；\n"
                           f"当前{'已' if self._enabled_blacklist else '未'}启用黑名单，"
                           f"已设置 {count[3]} 个黑名单插件库，"
                           f"全部插件库中，总共有 {count[4]} 个命中了黑名单插件库；"
                           f"本次发现的新插件库中，命中了 {count[5]} 个黑名单插件库。")
                    __send_message(title=f"{self.plugin_name} - 更新推送", text=msg)
                else:
                    logger.info("未检查到网页记录的插件库地址有更新，无需通知")

            if mode == "write" and self._enabled_write_notify:
                settings_msg = f'更新系统配置中的插件库地址{"成功" if settings_flag else "失败"}' if settings_flag else ""
                env_msg = f'更新app.env中的插件库地址 {"成功" if env_flag else "失败"}' if env_flag else ""
                __send_message(title=f"{self.plugin_name} - 执行结果推送", text=f"{settings_msg}\n{env_msg}\n")
        except Exception as e:
            logger.error(f"处理通知失败 - {e}")

    """ 统计 """

    def __update_and_save_statistic_info(self, all_markets_list: Tuple, wiki_markets_list: Optional[list],
                                         update_time: str):
        """
        更新并保存统计信息
        """
        _, full_markets_list, other_markets_list, _, _, full_in_blacklist_markets_list, _ = all_markets_list

        statistic_info: dict[str, Any] = self.__get_statistic_info()
        env_markets_list = self.get_env_markets_list()
        settings_markets_list = self.__valid_markets_list(plugin_markets=settings.PLUGIN_MARKET, mode="当前配置")

        # 总库数量
        full_markets_count = len(full_markets_list)
        # 官方库数量
        wiki_markets_count = len(wiki_markets_list)
        # 非官方库数量
        other_markets_count = len(other_markets_list)

        # 正在使用的库数量
        settings_markets_count = len(settings_markets_list)
        # ENV中的库数量
        env_markets_count = len(env_markets_list)
        # 在full在黑名单中的库数量
        in_blacklist_markets_count = len(full_in_blacklist_markets_list)

        # 头部统计信息
        statistic_info.update({
            "full_markets_count": full_markets_count,
            "wiki_markets_count": wiki_markets_count,
            "other_markets_count": other_markets_count,

            "settings_markets_count": settings_markets_count,
            "env_markets_count": env_markets_count,
            "in_blacklist_markets_count": in_blacklist_markets_count,

            "update_time": update_time,
        })

        # 重新生成数据列表
        data_list = {}

        for plugin_market in full_markets_list:
            user, repo, branch = self.__get_repo_info(repo_url=plugin_market)
            source = "官网" if plugin_market in wiki_markets_list else "第三方"
            if plugin_market not in full_in_blacklist_markets_list:
                if plugin_market in settings_markets_list and plugin_market in env_markets_list:
                    status = "写入ENV并使用"
                elif plugin_market in settings_markets_list and plugin_market not in env_markets_list:
                    status = "仅配置"
                elif plugin_market not in settings_markets_list and plugin_market in env_markets_list:
                    status = "仅写入ENV"
                else:
                    status = "未使用"
            else:
                status = "命中黑名单"

            data_list[plugin_market] = {
                "source": source,
                "status": status,
                "user": user,
                "repo": repo,
                "branch": branch,
                "url": plugin_market,
            }

        self.save_data("statistic", statistic_info)
        self.save_data("data_list", data_list)

    def __get_statistic_info(self) -> Dict[str, int]:
        """
        获取统计数据
        """
        statistic_info: dict[str, Any] = self.get_data("statistic") or {
            "full_markets_count": 0,
            "wiki_markets_count": 0,
            "other_markets_count": 0,

            "settings_markets_count": 0,
            "env_markets_count": 0,
            "in_blacklist_markets_count": 0,

            "update_time": 0,

        }
        return statistic_info

    @staticmethod
    def __get_repo_info(repo_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        获取Github仓库信息
        :param repo_url: Github仓库地址
        :return: user, repo, branch
        """
        # Todo；后续考虑支持非main分支，需要主程序支持
        if not repo_url:
            return None, None, None
        if not repo_url.endswith("/"):
            repo_url += "/"
        if repo_url.count("/") < 6:
            repo_url = f"{repo_url}main/"
        try:
            user, repo, branch = repo_url.split("/")[-4:-1]
        except Exception as e:
            logger.error(f"解析Github仓库地址失败：{str(e)} - {traceback.format_exc()}")
            return None, None, None
        return user, repo, branch

    def __get_total_elements(self) -> List[dict]:
        """
        组装汇总元素
        """
        # 统计数据
        statistic_info: dict[str, Any] = self.__get_statistic_info()

        full_markets_count = statistic_info.get("full_markets_count") or 0
        wiki_markets_count = statistic_info.get("wiki_markets_count") or 0
        other_markets_count = statistic_info.get("other_markets_count") or 0

        settings_markets_count = statistic_info.get("settings_markets_count") or 0
        env_markets_count = statistic_info.get("env_markets_count") or 0
        in_blacklist_markets_count = statistic_info.get("in_blacklist_markets_count") or 0

        update_time = statistic_info.get("update_time") or "暂无记录"

        if full_markets_count == 0:
            all_markets_count = "暂无记录"
        else:
            all_markets_count = f"{full_markets_count} / {wiki_markets_count} / {other_markets_count}"

        if full_markets_count == 0 and env_markets_count == 0:
            conf_markets_count = "暂无记录"
        else:
            conf_markets_count = f"{settings_markets_count} / {env_markets_count} / {in_blacklist_markets_count}"

        return [
            # 库数量
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 4,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [

                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '全部插件库 / 官方 / 非官方'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': all_markets_count
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
            # 配置库数量
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 4,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '当前使用配置 / ENV中配置 / 命中黑名单'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': conf_markets_count
                                                    }
                                                ]
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                ]
            },
            # 上次更新时间
            {
                'component': 'VCol',
                'props': {
                    'cols': 12,
                    'md': 4,
                    'sm': 6
                },
                'content': [
                    {
                        'component': 'VCard',
                        'props': {
                            'variant': 'tonal',
                        },
                        'content': [
                            {
                                'component': 'VCardText',
                                'props': {
                                    'class': 'd-flex align-center',
                                },
                                'content': [
                                    {
                                        'component': 'div',
                                        'content': [
                                            {
                                                'component': 'span',
                                                'props': {
                                                    'class': 'text-caption'
                                                },
                                                'text': '上次更新时间'
                                            },
                                            {
                                                'component': 'div',
                                                'props': {
                                                    'class': 'd-flex align-center flex-wrap'
                                                },
                                                'content': [
                                                    {
                                                        'component': 'span',
                                                        'props': {
                                                            'class': 'text-h6'
                                                        },
                                                        'text': update_time
                                                    },
                                                ]
                                            },
                                        ]
                                    },
                                ]
                            }
                        ]
                    }
                ]
            },
        ]

    """ 配置更新 """

    def __update_config(self):
        """
        更新配置
        """
        config = {
            "enabled": self._enabled,
            "onlyonce": self._onlyonce,
            "corn": self._corn,
            "enabled_update_notify": self._enabled_update_notify,
            "enabled_write_notify": self._enabled_write_notify,
            "notify_type": self._notify_type,

            "enabled_write_new_markets": self._enabled_write_new_markets,
            "enabled_write_new_markets_to_env": self._enabled_write_new_markets_to_env,
            "enabled_blacklist": self._enabled_blacklist,
            "blacklist": self._blacklist,

            "enabled_auto_get": self._enabled_auto_get,
            "enabled_proxy": self._enabled_proxy,
            "timeout": self._timeout,
            "wiki_url": self._wiki_url,
            "wiki_url_xpath": self._wiki_url_xpath,

            "last_wiki_markets_list": self.last_wiki_markets_list,
            "last_blacklist_markets_list": self._blacklist,
        }
        self.update_config(config)
