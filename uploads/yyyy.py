from openai import OpenAI

# 【唯一正确配置】一个字都别改！
client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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"  # 只改这里！
)

# 用官方免费白名单模型
completion = client.chat.completions.create(
    model="z-ai/glm-4.7",
    messages=[{"role": "user", "content": "你好"}],
)

print(completion.choices[0].message.content)