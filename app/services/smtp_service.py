"""SMTP 邮件服务模块"""
import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class SMTPConfig:
    """SMTP 配置类"""
    def __init__(
        self,
        host: str,
        port: int = 587,
        username: str = "",
        password: str = "",
        sender: str = "",
        use_tls: bool = True
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.sender = sender
        self.use_tls = use_tls


class SMTPService:
    """SMTP 邮件服务"""
    
    def __init__(self, config: SMTPConfig):
        self.config = config
        self.template_path = Path(__file__).parent.parent / "templates" / "email_notification.html"
    
    def _load_template(self) -> str:
        """加载邮件模板"""
        try:
            with open(self.template_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"Failed to load email template: {e}")
            # 返回简单模板作为 fallback
            return """<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body>
<h2>{{subject}}</h2>
<p><strong>严重程度:</strong> {{severity_text}}</p>
<p><strong>时间:</strong> {{timestamp}}</p>
<p><strong>来源:</strong> {{issuer}}</p>
<hr>
<p>{{content}}</p>
</body>
</html>"""
    
    def _render_template(
        self,
        subject: str,
        content: str,
        severity: str = "info",
        issuer: str = "IPTV Manager"
    ) -> str:
        """渲染邮件模板"""
        template = self._load_template()
        
        # 严重程度映射
        severity_map = {
            "info": ("信息", "#409eff"),
            "warning": ("警告", "#e6a23c"),
            "error": ("错误", "#f56c6c")
        }
        severity_text, severity_color = severity_map.get(severity, ("信息", "#409eff"))
        
        # 替换变量
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        html = template.replace("{{subject}}", subject)
        html = html.replace("{{content}}", content.replace("\n", "<br>"))
        html = html.replace("{{severity_text}}", severity_text)
        html = html.replace("{{severity_color}}", severity_color)
        html = html.replace("{{issuer}}", issuer)
        html = html.replace("{{timestamp}}", timestamp)
        
        return html
    
    def test_connection(self) -> tuple[bool, str]:
        """测试 SMTP 连接
        
        Returns:
            (success, message)
        """
        try:
            if self.config.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.config.host, self.config.port, timeout=10) as server:
                    server.starttls(context=context)
                    server.login(self.config.username, self.config.password)
            else:
                with smtplib.SMTP(self.config.host, self.config.port, timeout=10) as server:
                    server.login(self.config.username, self.config.password)
            
            return True, "连接成功"
        except smtplib.SMTPAuthenticationError:
            return False, "认证失败，请检查用户名和密码"
        except smtplib.SMTPConnectError:
            return False, "连接失败，请检查服务器地址和端口"
        except Exception as e:
            return False, f"连接错误: {str(e)}"
    
    def send_test_email(self, recipient: Optional[str] = None) -> tuple[bool, str]:
        """发送测试邮件
        
        Args:
            recipient: 收件人邮箱，默认为发件人
            
        Returns:
            (success, message)
        """
        if not recipient:
            recipient = self.config.sender
        
        subject = "IPTV Manager - SMTP 测试邮件"
        content = """这是一封测试邮件。

如果您收到此邮件，说明您的 SMTP 配置正确，可以正常接收 IPTV Manager 的系统通知。

通知功能包括：
- 订阅源刷新失败提醒
- 系统状态异常警告
- 直播流不可达阈值提醒
- 频道可用性监控

感谢您使用 IPTV Manager！"""
        
        return self.send_email(
            recipient=recipient,
            subject=subject,
            content=content,
            severity="info",
            issuer="系统测试"
        )
    
    def send_email(
        self,
        recipient: str,
        subject: str,
        content: str,
        severity: str = "info",
        issuer: str = "IPTV Manager"
    ) -> tuple[bool, str]:
        """发送邮件
        
        Args:
            recipient: 收件人邮箱
            subject: 邮件主题
            content: 邮件内容
            severity: 严重程度 (info/warning/error)
            issuer: 发送者标识
            
        Returns:
            (success, message)
        """
        try:
            # 创建邮件
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = self.config.sender
            msg['To'] = recipient
            
            # 渲染 HTML 内容
            html_content = self._render_template(subject, content, severity, issuer)
            
            # 添加 HTML 部分
            html_part = MIMEText(html_content, 'html', 'utf-8')
            msg.attach(html_part)
            
            # 发送邮件
            if self.config.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.config.host, self.config.port, timeout=10) as server:
                    server.starttls(context=context)
                    server.login(self.config.username, self.config.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.config.host, self.config.port, timeout=10) as server:
                    server.login(self.config.username, self.config.password)
                    server.send_message(msg)
            
            return True, "邮件发送成功"
            
        except Exception as e:
            return False, f"发送失败: {str(e)}"


def create_smtp_service_from_config(config_dict: dict) -> SMTPService:
    """从配置字典创建 SMTP 服务"""
    smtp_config = SMTPConfig(
        host=config_dict.get('host', ''),
        port=config_dict.get('port', 587),
        username=config_dict.get('username', ''),
        password=config_dict.get('password', ''),
        sender=config_dict.get('sender', ''),
        use_tls=config_dict.get('use_tls', True)
    )
    return SMTPService(smtp_config)
