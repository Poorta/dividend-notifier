# 测试配置加载
from app.config import settings

print("=== Dividend Notifier 配置加载测试 ===\n")
print(f"📧 邮件配置:")
print(f"   host: {settings.mail.host}:{settings.mail.port}")
print(f"   recipients: {settings.mail.recipients}")
print(f"\n📊 筛选阈值:")
print(f"   连续派现 >= {settings.filter.min_consecutive_years} 年")
print(f"   排除ST: {settings.filter.exclude_st}")
print(f"   市值下限: {settings.filter.min_market_cap}")
print(f"   股息率下限: {settings.filter.min_dividend_yield}")
print(f"\n🎨 颜色阈值:")
print(f"   股息率红 >= {settings.color.div_yield_red}%, 绿 < {settings.color.div_yield_green}%")
print(f"\n⏰ 推送时间: {settings.send_hour:02d}:{settings.send_minute:02d}")
print(f"\n📁 输出目录: {settings.output.output_dir}")
print(f"\n✅ 配置加载成功!")
