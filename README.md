# MYBUZZ News Bot V1.1

自动抓取马来西亚新闻，并按 MYBUZZ 比例输出/发布：
- 40% 📰 News
- 25% 🔥 Viral
- 15% 🎬 Entertainment
- 10% 🍜 Food / Lifestyle
- 10% 📱 Tech / Gadget

## 这版新增
1. Telegram Bot API 自动发布
2. 中文 + Bahasa Melayu 双语摘要（有 OPENAI_API_KEY 时启用 AI；没有则安全回退）
3. `.env` 自动读取
4. Telegram 发送成功才写入 seen，避免发送失败却被误标记
5. `MYBUZZ_DRY_RUN=true` 可先测试，不实际发频道

## 第一步：准备 API
- GNews API Key：用于抓取新闻
- Telegram Bot Token：从 BotFather 创建 bot 后取得
- Telegram Channel：把 bot 加为管理员，并填写 `@channelusername`
- 可选 OpenAI API Key：用于把新闻整理成中文 + 马来文；没有也可以运行

## 第二步：安装
Python 3.10+。本项目只使用 Python 标准库，不需要 pip package。

## 第三步：配置
复制：
`.env.example` → `.env`

填写：
`GNEWS_API_KEY=...`
`TELEGRAM_BOT_TOKEN=...`
`TELEGRAM_CHAT_ID=@你的频道username`

先保持：
`MYBUZZ_TELEGRAM_SEND=false`
`MYBUZZ_DRY_RUN=true`

## 第四步：测试
`python mybuzz_news_bot.py`

确认新闻、分类、双语内容和链接都正常。

## 第五步：正式自动发 Telegram
改成：
`MYBUZZ_TELEGRAM_SEND=true`
`MYBUZZ_DRY_RUN=false`

然后运行程序即可自动发布。

## 推荐运行频率
第一版建议每 2 小时跑一次。之后再加入排程、图片、热门度评分、人工审核和多来源事件去重。
