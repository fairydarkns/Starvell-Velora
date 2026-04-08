"""
Конфигурация бота
"""

import configparser
import ast
import json
from pathlib import Path
from typing import List, Dict, Any, Union


class ConfigManager:
    """Управление конфигурацией в CFG формате"""
    
    def __init__(self, config_path: str = "configs/_main.cfg", create_if_missing: bool = False):
        self.config_path = Path(config_path)
        self._config = configparser.ConfigParser()
        self.create_if_missing = create_if_missing
        self._load_or_create()
        
    def _load_or_create(self):
        """Загрузить или создать конфигурацию"""
        if self.config_path.exists():
            try:
                # Пробуем UTF-8
                self._config.read(self.config_path, encoding='utf-8')
                # После загрузки проверим целостность/схему конфигурации 
                try:
                    self._sanitize_config()
                except Exception:
                    # Не ломаем загрузку конфигурации при ошибках очистки
                    pass
            except UnicodeDecodeError:
                try:
                    # Если не получилось, пробуем Windows-1251
                    self._config.read(self.config_path, encoding='cp1251')
                    # Пересохраняем в UTF-8
                    self.save()
                except Exception:
                    if self.create_if_missing:
                        self._create_default()
                    else:
                        self._config.clear()
            except Exception:
                if self.create_if_missing:
                    self._create_default()
                else:
                    self._config.clear()
        else:
            if self.create_if_missing:
                self._create_default()
            
    def _create_default(self):
        """Создать конфигурацию по умолчанию"""
        self._config['Starvell'] = {
            'session_cookie': '',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'autoRaise': 'false',
            'autoDelivery': 'false',
            'autoRestore': 'false',
            'autoRead': 'true',
            'locale': 'ru',
            'autoTicket': 'false',
            'autoTicketInterval': '3600',
            'autoTicketMaxOrders': '5',
            'autoTicketOrderAge': '48'
        }
        
        self._config['Telegram'] = {
            'enabled': 'true',
            'token': '',
            'secretKeyHash': ''
        }
        
        self._config['Notifications'] = {
            'checkInterval': '30',
            'newMessages': 'true',
            'allMessages': 'false',
            'includeOwnMessages': 'false',
            'newOrders': 'true',
            'supportMessages': 'true',
            'lotRestore': 'false',
            'botStart': 'false',
            'botStop': 'false',
            'lotDeactivate': 'false',
            'lotBump': 'false',
            'autoTicket': 'true',
            'orderConfirmed': 'false',
            'review': 'false',
            'reviewDeleted': 'false',
            'autoResponses': 'false',
        }

        self._config['AutoResponse'] = {
            'orderConfirm': 'false',
            'orderConfirmText': 'Спасибо за покупку! Если возникнут вопросы - обращайтесь.',
            'reviewResponse': 'false',
            'reviewResponseText': 'Благодарю за отзыв! Рад был помочь.'
        }
        
        self._config['Monitor'] = { # Устарело, оставить для совместимости
            'chatPollInterval': '5',
            'ordersPollInterval': '10',
            'remoteInfoInterval': '120'
        }
        
        self._config['AutoRaise'] = {
            'enabled': 'false',
            'interval': '3600'
        }
        
        self._config['Storage'] = {
            'dir': 'storage'
        }
        self._config['StarvellProxy'] = {
            'enabled': 'false',
            'host': '',
            'port': '',
            'username': '',
            'password': '',
        }
        self._config['TelegramProxy'] = {
            'enabled': 'false',
            'scheme': 'http',
            'host': '',
            'port': '',
            'username': '',
            'password': '',
        }
        
        self._config['KeepAlive'] = {
            'enabled': 'true'
        }
        
        self._config['Other'] = {
            'debug': 'false',
            'watermark': '🤖',
            'useWatermark': 'true'
        }
        
        self._config['AutoTicket'] = {
            'ticketType': '1',
            'orderUserTypeId': '2',
            'orderTopicId': '501'
        }
        
        self.save()

    def _get_default_template(self) -> Dict[str, Dict[str, str]]:
        """Вернуть шаблон секций и ключей по умолчанию (как словарь).

        Используется для валидации/синхронизации существующего файла конфига.
        """
        return {
            'Starvell': {
                'session_cookie': '',
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'autoRaise': 'false',
                'autoDelivery': 'false',
                'autoRestore': 'false',
                'autoRead': 'true',
                'locale': 'ru',
                'autoTicket': 'false',
                'autoTicketInterval': '3600',
                'autoTicketMaxOrders': '5',
                'autoTicketOrderAge': '48'
            },
            'Telegram': {
                'enabled': 'true',
                'token': '',
                'secretKeyHash': ''
            },
            'Notifications': {
                'checkInterval': '30',
                'newMessages': 'true',
                'allMessages': 'false',
                'includeOwnMessages': 'false',
                'newOrders': 'true',
                'supportMessages': 'true',
                'lotRestore': 'false',
                'botStart': 'false',
                'botStop': 'false',
                'lotDeactivate': 'false',
                'lotBump': 'false',
                'autoTicket': 'true',
                'orderConfirmed': 'false',
                'review': 'false',
                'autoResponses': 'false',
            },
            'AutoResponse': {
                'orderConfirm': 'false',
                'orderConfirmText': 'Спасибо за покупку! Если возникнут вопросы - обращайтесь.',
                'reviewResponse': 'false',
                'reviewResponseText': 'Благодарю за отзыв! Рад был помочь.'
            },
            'Monitor': {
                'chatPollInterval': '5',
                'ordersPollInterval': '10',
                'remoteInfoInterval': '120'
            },
            'AutoRaise': {
                'enabled': 'false',
                'interval': '3600'
            },
            'Storage': {
                'dir': 'storage'
            },
            'StarvellProxy': {
                'enabled': 'false',
                'host': '',
                'port': '',
                'username': '',
                'password': '',
            },
            'TelegramProxy': {
                'enabled': 'false',
                'scheme': 'http',
                'host': '',
                'port': '',
                'username': '',
                'password': '',
            },
            'KeepAlive': {
                'enabled': 'true'
            },
            'Other': {
                'debug': 'false',
                'watermark': '🤖',
                'useWatermark': 'true',
                'log_level': 'INFO',
                'timezone': 'Europe/Moscow',
            },
            'AutoTicket': {
                'ticketType': '1',
                'orderUserTypeId': '2',
                'orderTopicId': '501'
            }
        }

    def _sanitize_config(self):
        """Синхронизировать текущий конфиг со схемой по умолчанию.

        Удаляет лишние секции/ключи и добавляет отсутствующие ключи с
        дефолтными значениями.
        """
        default = self._get_default_template()
        changes_made = False

        # Удаляем лишние секции (те, которые не описаны в шаблоне)
        for section in list(self._config.sections()):
            if section not in default:
                del self._config[section]
                changes_made = True

        for section, keys in default.items():
            if not self._config.has_section(section):
                # Если секции нет - создаём и добавляем все ключи с дефолтами
                self._config.add_section(section)
                for key, val in keys.items():
                    self._config.set(section, key, val)
                changes_made = True
                continue

            # Если секция есть - удаляем ключи, не описанные в шаблоне
            # Сравниваем имена ключей в нижнем регистре, чтобы быть
            # нечувствительными к изменению регистра optionxform
            allowed = set(k.lower() for k in keys.keys())
            for key in list(self._config[section].keys()):
                if key.lower() not in allowed:
                    self._config.remove_option(section, key)
                    changes_made = True
   
            # Добавляем отсутствующие ключи (не перезаписываем существующие)
            for key, val in keys.items():
                if not self._config.has_option(section, key):
                    self._config.set(section, key, val)
                    changes_made = True

        # Сохраняем изменения ТОЛЬКО если что-то изменилось
        if changes_made:
            self.save()
            import logging
            logger = logging.getLogger(__name__)
            logger.info("🔧 Конфигурация синхронизирована с новой версией")
        
    def save(self):
        """Сохранить конфигурацию"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            self._config.write(f)
            
    def _parse_value(self, value: str) -> Union[str, int, bool, list]:
        """Парсинг значения из строки"""
        # Сначала пытаемся преобразовать в list
        if value.startswith('[') and value.endswith(']'):
            try:
                return ast.literal_eval(value)
            except:
                pass
        
        # Пытаемся преобразовать в int (до bool, чтобы '1' не стало True)
        try:
            return int(value)
        except ValueError:
            pass
        
        # Пытаемся преобразовать в bool
        if value.lower() in ('true', 'yes', 'on'):
            return True
        if value.lower() in ('false', 'no', 'off'):
            return False
                
        # Возвращаем как строку
        return value
            
    def get(self, section: str, key: str, default=None):
        """Получить значение (например: 'Telegram', 'token')"""
        try:
            value = self._config.get(section, key)
            return self._parse_value(value)
        except:
            return default
        
    def set(self, section: str, key: str, value):
        """Установить значение"""
        if not self._config.has_section(section):
            self._config.add_section(section)
            
        # Преобразуем значение в строку
        if isinstance(value, bool):
            str_value = 'true' if value else 'false'
        elif isinstance(value, list):
            str_value = str(value)
        else:
            str_value = str(value)
            
        self._config.set(section, key, str_value)
        self.save()
        
    def get_all(self) -> Dict[str, Any]:
        """Получить всю конфигурацию"""
        result = {}
        for section in self._config.sections():
            result[section] = {}
            for key, value in self._config.items(section):
                result[section][key] = self._parse_value(value)
        return result


# Глобальный экземпляр конфигурации
_config_manager = ConfigManager(create_if_missing=False)


class BotConfig:
    """Конфигурация бота"""

    @staticmethod
    def _admins_registry_path() -> Path:
        return Path(BotConfig.STORAGE_DIR()) / "telegram" / "admins.json"

    @staticmethod
    def _default_admin_entry() -> Dict[str, Any]:
        return {
            "enabled": True,
            "bot_start": True,
            "bot_stop": False,
            "new_messages": True,
            "new_orders": True,
            "support_messages": True,
            "order_completed": True,
            "order_confirmed": True,
            "backup_created": True,
            "backup_failed": True,
            "update_started": True,
            "update_finished": True,
            "update_failed": True,
            "errors": True,
        }

    @classmethod
    def _read_admin_registry(cls) -> Dict[str, Any]:
        path = cls._admins_registry_path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        if not isinstance(payload, dict):
            return {}
        normalized: Dict[str, Any] = {}
        for admin_id, prefs in payload.items():
            normalized[str(admin_id)] = cls._default_admin_entry() | (prefs or {})
        return normalized

    @classmethod
    def _write_admin_registry(cls, payload: Dict[str, Any]) -> None:
        path = cls._admins_registry_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def reload(cls):
        """Перезагрузить конфигурацию"""
        global _config_manager
        _config_manager = ConfigManager(create_if_missing=False)
    
    # === Telegram ===
    @staticmethod
    def BOT_TOKEN() -> str:
        return _config_manager.get('Telegram', 'token', '')
    
    @staticmethod
    def PASSWORD_HASH() -> str:
        return _config_manager.get('Telegram', 'secretKeyHash', '')
    
    @classmethod
    def ADMIN_IDS(cls) -> list:
        return [int(admin_id) for admin_id in cls._read_admin_registry().keys()]
    
    @classmethod
    def set_admin_ids(cls, admin_ids: list):
        """Установить список админов в storage/telegram/admins.json"""
        existing = cls._read_admin_registry()
        normalized: Dict[str, Any] = {}
        for admin_id in admin_ids:
            try:
                key = str(int(admin_id))
            except Exception:
                continue
            normalized[key] = cls._default_admin_entry() | existing.get(key, {})
        cls._write_admin_registry(normalized)
    
    # === Starvell ===
    @staticmethod
    def STARVELL_SESSION() -> str:
        return _config_manager.get('Starvell', 'session_cookie', '')
    
    @staticmethod
    def USER_AGENT() -> str:
        default_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        return _config_manager.get('Starvell', 'user_agent', default_ua)
    
    # === Прокси ===
    @staticmethod
    def PROXY_ENABLED() -> bool:
        return _config_manager.get('StarvellProxy', 'enabled', False)
    
    @staticmethod
    def PROXY_IP() -> str:
        return _config_manager.get('StarvellProxy', 'host', '')
    
    @staticmethod
    def PROXY_PORT() -> str:
        return _config_manager.get('StarvellProxy', 'port', '')
    
    @staticmethod
    def PROXY_LOGIN() -> str:
        return _config_manager.get('StarvellProxy', 'username', '')
    
    @staticmethod
    def PROXY_PASSWORD() -> str:
        return _config_manager.get('StarvellProxy', 'password', '')
    
    @staticmethod
    def PROXY_CHECK() -> bool:
        """Проверять ли прокси перед использованием"""
        return False
    
    @staticmethod
    def PROXY() -> str:
        """
        Получить прокси строку (если включен)
        Формат: [login:password@]ip:port
        """
        if not BotConfig.PROXY_ENABLED():
            return ''
        host = BotConfig.PROXY_IP()
        port = BotConfig.PROXY_PORT()
        if not host or not port:
            return ''
        login = BotConfig.PROXY_LOGIN()
        password = BotConfig.PROXY_PASSWORD()
        if login:
            auth = login
            if password:
                auth = f"{auth}:{password}"
            return f"http://{auth}@{host}:{port}"
        return f"http://{host}:{port}"
    
    @staticmethod
    def set_proxy(ip: str, port: str, login: str = '', password: str = '', enabled: bool = True, check: bool = False):
        """Установить прокси"""
        _config_manager.set('StarvellProxy', 'enabled', enabled)
        _config_manager.set('StarvellProxy', 'host', ip)
        _config_manager.set('StarvellProxy', 'port', port)
        _config_manager.set('StarvellProxy', 'username', login)
        _config_manager.set('StarvellProxy', 'password', password)

    @staticmethod
    def TELEGRAM_PROXY_ENABLED() -> bool:
        return _config_manager.get('TelegramProxy', 'enabled', False)

    @staticmethod
    def TELEGRAM_PROXY_SCHEME() -> str:
        return _config_manager.get('TelegramProxy', 'scheme', 'http')

    @staticmethod
    def TELEGRAM_PROXY_HOST() -> str:
        return _config_manager.get('TelegramProxy', 'host', '')

    @staticmethod
    def TELEGRAM_PROXY_PORT() -> str:
        return _config_manager.get('TelegramProxy', 'port', '')

    @staticmethod
    def TELEGRAM_PROXY_LOGIN() -> str:
        return _config_manager.get('TelegramProxy', 'username', '')

    @staticmethod
    def TELEGRAM_PROXY_PASSWORD() -> str:
        return _config_manager.get('TelegramProxy', 'password', '')

    @staticmethod
    def TELEGRAM_PROXY() -> str:
        if not BotConfig.TELEGRAM_PROXY_ENABLED():
            return ''
        host = BotConfig.TELEGRAM_PROXY_HOST()
        port = BotConfig.TELEGRAM_PROXY_PORT()
        if not host or not port:
            return ''
        scheme = BotConfig.TELEGRAM_PROXY_SCHEME() or 'http'
        login = BotConfig.TELEGRAM_PROXY_LOGIN()
        password = BotConfig.TELEGRAM_PROXY_PASSWORD()
        if login:
            auth = login
            if password:
                auth = f"{auth}:{password}"
            return f"{scheme}://{auth}@{host}:{port}"
        return f"{scheme}://{host}:{port}"
    
    # === Хранилище ===
    @staticmethod
    def STORAGE_DIR() -> str:
        return _config_manager.get('Storage', 'dir', 'storage')
    
    # === Уведомления ===
    @staticmethod
    def CHECK_INTERVAL() -> int:
        return _config_manager.get('Notifications', 'checkInterval', 30)
    
    @staticmethod
    def NOTIFY_NEW_MESSAGES() -> bool:
        return _config_manager.get('Notifications', 'newMessages', True)

    @staticmethod
    def NOTIFY_ALL_MESSAGES() -> bool:
        """Уведомлять о всех новых сообщениях, а не только о непрочитанных."""
        return _config_manager.get('Notifications', 'allMessages', False)

    @staticmethod
    def NOTIFY_OWN_MESSAGES() -> bool:
        """Уведомлять о сообщениях, отправленных самим продавцом."""
        return _config_manager.get('Notifications', 'includeOwnMessages', False)
    
    @staticmethod
    def NOTIFY_NEW_ORDERS() -> bool:
        return _config_manager.get('Notifications', 'newOrders', True)
    
    @staticmethod
    def NOTIFY_SUPPORT_MESSAGES() -> bool:
        return _config_manager.get('Notifications', 'supportMessages', True)
    
    @staticmethod
    def NOTIFY_LOT_RESTORE() -> bool:
        return _config_manager.get('Notifications', 'lotRestore', True)
    
    @staticmethod
    def NOTIFY_BOT_START() -> bool:
        return _config_manager.get('Notifications', 'botStart', True)

    @staticmethod
    def NOTIFY_BOT_STOP() -> bool:
        return _config_manager.get('Notifications', 'botStop', False)
    
    @staticmethod
    def NOTIFY_LOT_DEACTIVATE() -> bool:
        return _config_manager.get('Notifications', 'lotDeactivate', True)
    
    @staticmethod
    def NOTIFY_LOT_BUMP() -> bool:
        return _config_manager.get('Notifications', 'lotBump', False)

    @staticmethod
    def NOTIFY_AUTO_TICKET() -> bool:
        """Уведомлять об отправке авто-тикета"""
        return _config_manager.get('Notifications', 'autoTicket', True)

    @staticmethod
    def NOTIFY_ORDER_CONFIRMED() -> bool:
        """Уведомлять о подтверждении заказа"""
        return _config_manager.get('Notifications', 'orderConfirmed', False)

    @staticmethod
    def NOTIFY_REVIEW() -> bool:
        """Уведомлять о новых отзывах"""
        return _config_manager.get('Notifications', 'review', False)

    @staticmethod
    def NOTIFY_REVIEW_DELETED() -> bool:
        """Уведомлять об удалении отзывов"""
        return _config_manager.get('Notifications', 'reviewDeleted', False)

    @staticmethod
    def NOTIFY_AUTO_RESPONSES() -> bool:
        """Уведомлять при выполнении автоответов/команд"""
        return _config_manager.get('Notifications', 'autoResponses', False)
    
    # === Авто-поднятие ===
    @staticmethod
    def AUTO_BUMP_ENABLED() -> bool:
        return _config_manager.get('Starvell', 'autoRaise', False)
    
    @staticmethod
    def AUTO_BUMP_INTERVAL() -> int:
        return _config_manager.get('AutoRaise', 'interval', 3600)
    
    # === Авто-выдача ===
    @staticmethod
    def AUTO_DELIVERY_ENABLED() -> bool:
        return _config_manager.get('Starvell', 'autoDelivery', False)
    
    # === Авто-восстановление ===
    @staticmethod
    def AUTO_RESTORE_ENABLED() -> bool:
        return _config_manager.get('Starvell', 'autoRestore', False)
    
    # === Авто-прочтение ===
    @staticmethod
    def AUTO_READ_ENABLED() -> bool:
        """Автоматически помечать чаты как прочитанные"""
        return _config_manager.get('Starvell', 'autoRead', True)
    
    # === Авто-тикет ===
    @staticmethod
    def AUTO_TICKET_ENABLED() -> bool:
        """Автоматически отправлять тикеты для неподтверждённых заказов"""
        return _config_manager.get('Starvell', 'autoTicket', False)
    
    @staticmethod
    def AUTO_TICKET_INTERVAL() -> int:
        """Интервал проверки авто-тикета (секунды)"""
        return _config_manager.get('Starvell', 'autoTicketInterval', 3600)

    @staticmethod
    def AUTO_TICKET_MAX_ORDERS() -> int:
        """Максимум заказов в одном тикете"""
        return _config_manager.get('Starvell', 'autoTicketMaxOrders', 5)

    @staticmethod
    def AUTO_TICKET_ORDER_AGE() -> int:
        """Минимальный возраст заказа для авто-тикета (часы)"""
        return _config_manager.get('Starvell', 'autoTicketOrderAge', 48)
    
    @staticmethod
    def AUTO_TICKET_TYPE() -> str:
        """Тип тикета (из секции AutoTicket)"""
        return _config_manager.get('AutoTicket', 'ticketType', '1')
    
    @staticmethod
    def AUTO_TICKET_USER_TYPE_ID() -> str:
        """ID типа пользователя (из секции AutoTicket)"""
        return _config_manager.get('AutoTicket', 'orderUserTypeId', '2')
    
    @staticmethod
    def AUTO_TICKET_TOPIC_ID() -> str:
        """ID темы тикета (из секции AutoTicket)"""
        return _config_manager.get('AutoTicket', 'orderTopicId', '501')
    
    # === Автоответы ===
    @staticmethod
    def ORDER_CONFIRM_RESPONSE_ENABLED() -> bool:
        """Автоответ на подтверждение заказа"""
        return _config_manager.get('AutoResponse', 'orderConfirm', False)
    
    @staticmethod
    def ORDER_CONFIRM_RESPONSE_TEXT() -> str:
        """Текст автоответа на подтверждение заказа"""
        return _config_manager.get('AutoResponse', 'orderConfirmText', 'Спасибо за покупку! Если возникнут вопросы - обращайтесь.')
    
    @staticmethod
    def REVIEW_RESPONSE_ENABLED() -> bool:
        """Автоответ на отзыв"""
        return _config_manager.get('AutoResponse', 'reviewResponse', False)
    
    @staticmethod
    def REVIEW_RESPONSE_TEXT() -> str:
        """Текст автоответа на отзыв"""
        return _config_manager.get('AutoResponse', 'reviewResponseText', 'Благодарю за отзыв! Рад был помочь.')
    
    # === Вечный онлайн ===
    @staticmethod
    def KEEP_ALIVE_ENABLED() -> bool:
        """Поддерживать онлайн статус"""
        return _config_manager.get('KeepAlive', 'enabled', True)
    
    # === Чёрный список ===
    @staticmethod
    def BL_BLOCK_DELIVERY() -> bool:
        """Не выдавать товар пользователям из ЧС"""
        return _config_manager.get('Blacklist', 'block_delivery', True)
    
    @staticmethod
    def BL_BLOCK_RESPONSE() -> bool:
        """Не отвечать на команды пользователям из ЧС"""
        return _config_manager.get('Blacklist', 'block_response', True)
    
    @staticmethod
    def BL_BLOCK_MSG_NOTIF() -> bool:
        """Не уведомлять о сообщениях от пользователей из ЧС"""
        return _config_manager.get('Blacklist', 'block_msg_notifications', True)
    
    @staticmethod
    def BL_BLOCK_ORDER_NOTIF() -> bool:
        """Не уведомлять о заказах от пользователей из ЧС"""
        return _config_manager.get('Blacklist', 'block_order_notifications', True)
    
    @staticmethod
    def toggle_bl_setting(setting_key: str):
        """Переключить настройку чёрного списка"""
        current = _config_manager.get('Blacklist', setting_key, True)
        _config_manager.set('Blacklist', setting_key, not current)
    
    # === Debug ===
    @staticmethod
    def DEBUG() -> bool:
        return _config_manager.get('Other', 'debug', False)

    @staticmethod
    def WATERMARK() -> str:
        return _config_manager.get('Other', 'watermark', '🤖')

    @staticmethod
    def USE_WATERMARK() -> bool:
        return _config_manager.get('Other', 'useWatermark', True)
    
    @classmethod
    def validate(cls) -> bool:
        """Проверка конфигурации"""
        if not cls.BOT_TOKEN():
            raise ValueError("Telegram.token не установлен в _main.cfg")
        if not cls.STARVELL_SESSION():
            raise ValueError("Starvell.session_cookie не установлен в _main.cfg")
        return True
    
    @classmethod
    def _ensure_json_file(cls, path: Path, payload: Any):
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def ensure_dirs(cls):
        """Создать необходимые директории и базовые runtime-файлы"""
        storage_dir = Path(cls.STORAGE_DIR())
        storage_dir.mkdir(parents=True, exist_ok=True)
        (storage_dir / "cache").mkdir(exist_ok=True)
        (storage_dir / "marketplace").mkdir(exist_ok=True)
        (storage_dir / "plugins").mkdir(exist_ok=True)
        (storage_dir / "settings").mkdir(exist_ok=True)
        (storage_dir / "stats").mkdir(exist_ok=True)
        (storage_dir / "system").mkdir(exist_ok=True)
        (storage_dir / "telegram").mkdir(exist_ok=True)
        (storage_dir / "products").mkdir(exist_ok=True)
        Path("logs").mkdir(parents=True, exist_ok=True)
        Path("backups").mkdir(parents=True, exist_ok=True)
        Path("plugins").mkdir(parents=True, exist_ok=True)

        cls._ensure_json_file(storage_dir / "telegram" / "templates.json", [])
        cls._ensure_json_file(
            storage_dir / "telegram" / "custom_commands.json",
            {"prefix": "!", "enabled": False, "commands": []},
        )
        cls._ensure_json_file(storage_dir / "telegram" / "admins.json", {})
        cls._ensure_json_file(storage_dir / "telegram" / "state.json", {"last_bot_message_id": None})
        cls._ensure_json_file(
            storage_dir / "marketplace" / "state.json",
            {"account": {}, "threads": {}, "orders": {}},
        )
        cls._ensure_json_file(
            storage_dir / "system" / "update_state.json",
            {"last_backup": None, "last_update": None, "kept_backups": []},
        )
        cls._ensure_json_file(storage_dir / "stats" / "statistics.json", {})
    
    @classmethod
    def update(cls, **kwargs):
        """Обновить конфигурацию
        
        Пример: update(**{'auto_bump.enabled': True})
        Или: update(**{'Starvell.autoRaise': True})
        """
        for key, value in kwargs.items():
            if '.' in key:
                parts = key.split('.', 1)
                section_key = parts[0]
                cfg_key = parts[1]
                
                # Маппинг ключей на секции и параметры конфига
                if section_key == 'auto_bump' and cfg_key == 'enabled':
                    _config_manager.set('Starvell', 'autoRaise', value)
                elif section_key == 'auto_delivery' and cfg_key == 'enabled':
                    _config_manager.set('Starvell', 'autoDelivery', value)
                elif section_key == 'auto_restore' and cfg_key == 'enabled':
                    _config_manager.set('Starvell', 'autoRestore', value)
                elif section_key == 'auto_read' and cfg_key == 'enabled':
                    _config_manager.set('Starvell', 'autoRead', value)
                elif section_key == 'auto_ticket':
                    if cfg_key == 'enabled':
                        _config_manager.set('Starvell', 'autoTicket', value)
                    elif cfg_key == 'interval':
                        _config_manager.set('Starvell', 'autoTicketInterval', value)
                    elif cfg_key == 'max_orders':
                        _config_manager.set('Starvell', 'autoTicketMaxOrders', value)
                    elif cfg_key == 'order_age':
                        _config_manager.set('Starvell', 'autoTicketOrderAge', value)
                elif section_key == 'notifications':
                    if cfg_key == 'new_messages':
                        _config_manager.set('Notifications', 'newMessages', value)
                    elif cfg_key == 'all_messages':
                        _config_manager.set('Notifications', 'allMessages', value)
                    elif cfg_key == 'own_messages':
                        _config_manager.set('Notifications', 'includeOwnMessages', value)
                    elif cfg_key == 'auto_ticket':
                        _config_manager.set('Notifications', 'autoTicket', value)
                    elif cfg_key == 'new_orders':
                        _config_manager.set('Notifications', 'newOrders', value)
                    elif cfg_key == 'lot_restore':
                        _config_manager.set('Notifications', 'lotRestore', value)
                    elif cfg_key == 'bot_start':
                        _config_manager.set('Notifications', 'botStart', value)
                    elif cfg_key == 'bot_stop':
                        _config_manager.set('Notifications', 'botStop', value)
                    elif cfg_key == 'order_confirmed':
                        _config_manager.set('Notifications', 'orderConfirmed', value)
                    elif cfg_key == 'review':
                        _config_manager.set('Notifications', 'review', value)
                    elif cfg_key == 'review_deleted':
                        _config_manager.set('Notifications', 'reviewDeleted', value)
                    elif cfg_key == 'auto_responses':
                        _config_manager.set('Notifications', 'autoResponses', value)
                    elif cfg_key == 'lot_deactivate':
                        _config_manager.set('Notifications', 'lotDeactivate', value)
                    elif cfg_key == 'lot_bump':
                        _config_manager.set('Notifications', 'lotBump', value)
                    else:
                        # Прямая установка для других ключей
                        _config_manager.set('Notifications', cfg_key, value)
                elif section_key == 'other':
                    if cfg_key == 'use_watermark':
                        _config_manager.set('Other', 'useWatermark', value)
                    elif cfg_key == 'watermark':
                        _config_manager.set('Other', 'watermark', value)
                    else:
                        _config_manager.set('Other', cfg_key, value)
                else:
                    # Прямая установка секция.ключ
                    _config_manager.set(section_key, cfg_key, value)


# Получить менеджер конфигурации
def get_config_manager(reload: bool = False, create_if_missing: bool = False) -> ConfigManager:
    """Получить менеджер конфигурации"""
    global _config_manager
    if reload:
        _config_manager = ConfigManager(create_if_missing=create_if_missing)
    return _config_manager
