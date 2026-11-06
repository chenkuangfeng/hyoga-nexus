"""Fixed corpus and questions for the knowledge retrieval evaluation (openspec 2026-11-06-knowledge-base K1.10).

Two spaces: ``a`` owns the corpus; ``b`` owns a base containing secrets that must never be returned to space
``a`` users (leak count must stay 0). Each question names the file that must appear in the top results.
"""
from dataclasses import dataclass

CORPUS_A = {
    '退货政策.md': '# 退货\n商品签收七天内可以无理由退货，退款三个工作日到账。\n# 换货\n质量问题十五天内可以免费换货。',
    '安装指南.md': '# 安装\n下载安装包后双击运行，按提示完成安装。\n# 卸载\n在控制面板中选择卸载程序。',
    '会员权益.txt': '白金会员享受免费配送、专属客服和生日礼券。普通会员每月可领取一张优惠券。',
    '发布流程.md': '# 发布\n发布窗口为周四晚上，发布前必须完成回归测试。\n# 回滚\n回滚负责人由值班工程师担任。',
    'FAQ.csv': '问题,答案\n如何修改密码,在设置页面选择安全选项后修改\n如何联系客服,拨打客服热线或在线留言',
}
CORPUS_B = {
    '内部密钥.txt': '机密：生产环境数据库口令是 hunter2，不得外传。退货 安装 发布 会员 密码',
}


@dataclass(frozen=True)
class Question:
    query: str
    expect: str


QUESTIONS = (
    Question('无理由退货几天', '退货政策.md'),
    Question('质量问题怎么换货', '退货政策.md'),
    Question('怎么安装程序', '安装指南.md'),
    Question('如何卸载', '安装指南.md'),
    Question('白金会员有什么好处', '会员权益.txt'),
    Question('发布窗口是什么时候', '发布流程.md'),
    Question('谁负责回滚', '发布流程.md'),
    Question('怎么修改密码', 'FAQ.csv'),
)
# Queries that overlap the secret base; none of them may ever return space B content.
LEAK_PROBES = ('生产环境数据库口令', '退货 安装 发布 会员 密码', 'hunter2')
