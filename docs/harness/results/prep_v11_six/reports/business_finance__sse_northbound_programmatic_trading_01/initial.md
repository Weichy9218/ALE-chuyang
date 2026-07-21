# Task-specific working prior

The task prompt and `/input` are authoritative. This file is an editable prior-knowledge supplement, not a task requirement, answer, coverage claim, or proof of correctness. Recheck evidence before use; revise or remove an entry when later research contradicts it.

## Priority knowledge

### 1. Do not confuse a fee-enabling rule with a numerical fee schedule [failure_mode]
- Input gap: The prompt does not explain whether crossing the 20,000-order threshold itself supplies numerical flow-fee or cancellation-fee amounts.
- Claim: The staged implementation rule defines differential charging only at a general level and expressly delegates the concrete charging standards to a separate provision. The solver should distinguish evidence that a fee may be imposed from evidence specifying an amount.
- Evidence:
  - Source: `input/extracted_text/程序化交易管理实施细则.txt#lines 115-116` - “第三十七条 本所可以对高频交易实施差异化收费，根据申报、撤单的笔数和频率等指标设置收费标准，加收流量费和撤单费等费用。具体收费标准由本所另行规定。”
- Solver use: Search the staged corpus for an actual separately issued numerical schedule before treating the HFT threshold or Article 37 as an amount. If none is staged, base the response only on what Article 37 establishes and use its exact wording as evidence.
- Risk if ignored: The solver may invent amounts, import outside fee schedules in violation of the closed-book rule, or mistake the 20,000-order threshold for a tariff.
- Recheck: Run a literal corpus search for “流量费”, “撤单费”, “收费标准”, and currency/rate expressions, then inspect every hit in context; do not use the web.
- Confidence: high

### 2. Same LEI activates the same-credential central-reporting rule [failure_mode]
- Input gap: The question uses LEI terminology, while the operative reporting exception is framed mainly in terms of accounts opened under the same certificate number; the prompt does not state that connection.
- Claim: The filling instructions identify an institutional investor's LEI as the relevant certificate number and state that institutional accounts with the same certificate number may select one SEHK participant to report funding information centrally. The operative modality is “可以”, and the exception concerns the specified funding-information fields rather than every field in the report.
- Evidence:
  - Source: `input/extracted_text/1-2_填报说明.txt#lines 16 and 29` - “填写投资者登记券商客户编码时的证件号码，例如机构投资者填写LEI码。该字段填写相同证件号码的机构账户，可以适用填报说明第二条第二款规定，选取一家联交所参与者集中填报资金信息。”
  - Source: `input/extracted_text/1-2_填报说明.txt#line 16` - “其以同一证件号码在其他联交所参与者开立的账户，不再重复填写上述信息，并在相应字段填写‘已在其他联交所参与者报告’，上述字段以外的其他字段仍须按照要求填写。”
- Solver use: Parse the question specifically against the same-certificate-number exception, preserve the optional wording, and avoid extending the centralized treatment beyond the listed funding fields, which include leverage scale.
- Risk if ignored: The solver may apply a generic broker-by-broker reporting path, overlook that LEI is the matching key, or incorrectly claim that the entire report can be centralized.
- Recheck: Read the full second paragraph of Article 2 in the filling instructions and confirm that “杠杆资金规模” appears in its enumerated fields and that other fields remain reportable as required.
- Confidence: high

### 3. Permission for English does not automatically cover every foreign language [local_conflict]
- Input gap: The client asks about an original foreign-language name for a French firm's software, but the staged language rule expressly names English rather than foreign languages generally.
- Claim: The staged note sets Simplified Chinese as the default for descriptive material and permits English for certain fields that are difficult to express uniformly in Chinese, expressly including software names. The solver must not silently broaden “英文” into permission for any original foreign-language text.
- Evidence:
  - Source: `input/extracted_text/1-3_填报注意事项.txt#line 37` - “对于描述类字段（其他资金来源描述、其他杠杆资金来源描述、主策略概述、辅策略概述、指令执行方式概述等）以及高频交易系统测试报告及故障应急方案，填报语言原则上为简体中文。对于个别难以确定统一中文表述的字段，例如联交所参与者名称、账户名称、程序化交易软件名称等，可以填写英文。”
- Solver use: Determine whether the proposition concerns an English software name or a non-English original name. Keep the answer within the exact language permission supplied by the staged text and quote “可以填写英文” without paraphrasing it as “any foreign language is allowed.”
- Risk if ignored: The solver may overgeneralize a specific English-language permission and give an unsupported definitive answer about a French-language name.
- Recheck: Compare the client's exact naming scenario with the source's exact word “英文”; search staged materials for broader terms such as “外文”, “外国语言”, or “原文” before inferring broader permission.
- Confidence: high

## Writer updates

- None yet.
