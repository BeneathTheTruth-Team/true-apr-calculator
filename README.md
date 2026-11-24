# true-apr-calculator · 真实资金成本计算器

用现金流 IRR（内部收益率）揭示分期付款 / 消费信贷的真实年化成本。

## 项目简介与动机

很多分期产品宣传「每期手续费仅 0.6%」，听起来一年才 7.2%。但手续费始终按
**初始本金**收取，而你手里的本金每期都在减少——用现金流 IRR 计算，
「每期 0.6%、分 12 期」的真实名义年化成本约为 **13.03%**，接近宣传口径的两倍。
如果再叠加砍头息（放款时先扣一笔钱），成本还会进一步飙升。

本项目是一个零外部依赖的小工具，帮助普通用户看清分期的真实资金成本：

- 前端纯手写 HTML/CSS，图表只用 div 条形图和内联 SVG，**不引用任何
  CDN、字体、图标库、JS 库，断网状态全站完整可用**；
- 后端 Flask + 标准库 sqlite3，不调用任何网络 API，无登录/用户系统；
- 核心算法独立在 `calculator.py`，与 Web 层完全解耦，仅用标准库实现
  （不依赖 numpy / scipy / numpy_financial）。

## 功能列表

1. **分期计算器**：输入借款金额、期数、每期手续费率、可选砍头息，输出
   每期还款额、总利息、名义总费率、月 IRR、名义年化 IRR、有效年利率（EAR），
   并解释名义费率与 IRR/EAR 的差异；本金 vs 总利息条形图；现金流说明框。
   计算通过的方案自动存入 SQLite。
2. **方案对比**：列出所有已保存方案（创建时间倒序）并排比较，
   名义年化最高的方案醒目标记「成本最高」；支持删除方案。
3. **最低还款模拟**：输入欠款金额、月利率、每月还款比例，输出还清月数、
   总利息、逐月余额变化折线图（内联 SVG）与逐月明细表（首尾各若干月）。
   还款比例不高于月利率时明确报错。
4. **科普页**：手续费率 ≠ 利率、砍头息、等本等息 vs 等额本息，说人话、有例子。

## 安装运行

要求 Python 3.8+。

```bash
# 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 安装依赖（唯一第三方依赖：Flask）
pip install -r requirements.txt

# 启动
python app.py
```

浏览器打开 http://127.0.0.1:5000 。

## 目录结构

```
true-apr-calculator/
  app.py                    # Flask 路由、表单校验、SQLite 存取（Web 层）
  calculator.py             # 核心算法：现金流、NPV、IRR、年化、最低还款模拟
  tests/
    test_calculator.py      # 单元测试（标准库 unittest）
  templates/
    base.html               # 基础模板：导航、页脚免责声明
    index.html              # 分期计算器
    schemes.html            # 方案对比
    min_payment.html        # 最低还款模拟
    education.html          # 科普页
  static/
    style.css               # 全站样式（无外部资源）
  requirements.txt          # 唯一第三方依赖：Flask>=2.2,<4
  README.md
  LICENSE                   # MIT
  .gitignore
```

数据库文件在首次启动时自动创建于 `instance/true_apr.db`（已在 .gitignore 中忽略）。

## 算法简述

### 现金流定义

`cashflows_for_installment(principal, periods, fee_rate, upfront_fee=0.0)`：

- index 0 为期初放款（正数），之后每个 index 为一期期末还款（负数）；
- 若有砍头息，期初现金流 = `principal - upfront_fee`（你实际到手的钱）；
- 每期手续费 = `principal * fee_rate`（始终按初始本金计）；
- 每期还款 = `principal / periods + principal * fee_rate`。

### NPV

`npv(cashflows, rate)`：把每期现金流按 `(1 + rate) ** t` 折现到期初求和。

### 二分法求月 IRR

`monthly_irr(cashflows, tol=1e-10, max_iter=200)`：

1. 若 rate=0 时 NPV 已为 0（无手续费分期），直接返回 0.0；
2. 从区间 [0, 1] 开始找 NPV 变号区间；找不到则逐步把 high 翻倍
   （最多到 1024），仍无变号区间时返回 None，不硬猜；
3. 在区间内二分迭代至收敛。

### 年化口径

- 名义年化 = 月 IRR × 12；
- 有效年利率 EAR = (1 + 月 IRR)^12 − 1（考虑月复利，因此略高于名义年化）。

基准用例：1200 元 / 12 期 / 每期 0.6%，月 IRR ≈ 1.0862%，
名义年化 ≈ 13.03%，EAR ≈ 13.84%。

### 最低还款模拟口径与停止条件

`simulate_min_payment(balance, monthly_rate, payment_ratio, stop_balance=0.01, max_months=1200)`，
每月严格按以下顺序：

1. 先按还款前余额计息：`interest = balance * monthly_rate`；
2. 计息后余额 = `balance + interest`；
3. 当月还款 = `计息后余额 * payment_ratio`；
4. 若还款 ≥ 计息后余额，则全额结清。

停止条件：余额 ≤ `stop_balance` 视为还清；或达到 `max_months` 上限。
若 `payment_ratio <= monthly_rate`（每月还款不高于当月利息，余额永不下降），
抛出 `ValueError`。

基准用例：欠款 10000 元、月利率 1.5%、每月还 10%，约 153 个月还清，
总利息约 1734.10 元。

## 运行测试

```bash
python -m unittest discover tests -v
```

预期 17 个测试全部通过（OK）。

## 已知边界

- 仅模拟「等本等息」分期结构，不支持等额本息 / 等额本金的逐月摊还表；
- 不考虑逾期、提前还款、滞纳金等现实因素；
- IRR 求解在现金流无变号区间时返回 None（极端参数下结果可能缺失）；
- 金额内部用 float 计算，展示保留两位小数，存在浮点精度极限；
- 数据库为单文件 SQLite，适合个人本地使用，未做并发优化。

## 免责声明

本站所有结果均为「年化 IRR 估算」，用于帮助理解分期付款与消费信贷的真实
资金成本，**不构成监管口径的 APR，也不构成任何贷款、法律或投资建议**。
实际借款成本以合同与监管披露为准。

## License

MIT，见 [LICENSE](LICENSE)。
