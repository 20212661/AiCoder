from aicoder.tools.system_prompt import SystemPrompt
from aicoder.tools.spec import ToolSpec, ParamSpec


def make_prompt(mode="act"):
    sp = SystemPrompt()
    sp.configure(
        tools=[
            ToolSpec(name="read_file", description="Read", parameters=[ParamSpec(name="path")]),
            ToolSpec(name="search_files", description="Search", parameters=[ParamSpec(name="pattern")]),
            ToolSpec(name="list_files", description="List", parameters=[ParamSpec(name="path")]),
        ],
        cwd="/test",
        os_name="linux",
        model_list=["model-a"],
        current_model="model-a",
        mode=mode,
        ai_identity="",
    )
    return sp


# ── Sniff prompt structure ──


def test_sniff_prompt_contains_sniff_header():
    prompt = make_prompt(mode="sniff").build()
    assert "SNIFF" in prompt
    assert "嗅探模式" in prompt


def test_sniff_prompt_contains_sniff_report_template():
    prompt = make_prompt(mode="sniff").build()
    assert "嗅探报告" in prompt
    assert "发酵区概况" in prompt
    assert "构石痕迹" in prompt
    assert "异味来源" in prompt
    assert "污染扩散路径" in prompt
    assert "嗅探结论" in prompt
    assert "建议动作" in prompt


def test_sniff_prompt_contains_workflow():
    prompt = make_prompt(mode="sniff").build()
    assert "嗅探流程" in prompt
    assert "陌生仓库初探" in prompt
    assert "需求驱动嗅探" in prompt
    assert "故障驱动嗅探" in prompt


def test_sniff_prompt_contains_quality_standards():
    prompt = make_prompt(mode="sniff").build()
    assert "质量标准" in prompt
    assert "证据" in prompt


def test_sniff_prompt_contains_mode_switch_guidance():
    prompt = make_prompt(mode="sniff").build()
    assert "模式切换指引" in prompt
    assert "/plan" in prompt
    assert "/act" in prompt


def test_sniff_prompt_no_editing_section():
    prompt = make_prompt(mode="sniff").build()
    assert "EDITING FILES" not in prompt


def test_sniff_prompt_no_edit_capabilities():
    prompt = make_prompt(mode="sniff").build()
    assert "edit_file" not in prompt or "edit_file" not in prompt.split("CAPABILITIES")[1].split("RULES")[0]


def test_sniff_prompt_has_sniff_methodology():
    prompt = make_prompt(mode="sniff").build()
    assert "工作方法（嗅探模式）" in prompt
    assert "嗅探报告" in prompt


# ── Plan prompt (should NOT have sniff content) ──


def test_plan_prompt_does_not_contain_sniff_terms():
    prompt = make_prompt(mode="plan").build()
    assert "嗅探报告" not in prompt
    assert "发酵区概况" not in prompt
    assert "构石痕迹" not in prompt
    assert "异味来源" not in prompt
    assert "污染扩散路径" not in prompt
    assert "嗅探结论" not in prompt
    assert "建议动作" not in prompt


def test_plan_prompt_has_editing_section():
    prompt = make_prompt(mode="plan").build()
    assert "EDITING FILES" in prompt


# ── Act prompt ──


def test_act_prompt_has_editing_section():
    prompt = make_prompt(mode="act").build()
    assert "EDITING FILES" in prompt
    assert "edit_file" in prompt


def test_act_prompt_has_standard_methodology():
    prompt = make_prompt(mode="act").build()
    assert "WORK METHODOLOGY" in prompt
    assert "工作方法（嗅探模式）" not in prompt


# ── Sniff prompt references recon summary ──


def test_sniff_prompt_references_recon_summary():
    prompt = make_prompt(mode="sniff").build()
    assert "SNIFF RECON SUMMARY" in prompt or "侦察摘要" in prompt


def test_plan_prompt_does_not_reference_recon_summary():
    prompt = make_prompt(mode="plan").build()
    assert "SNIFF RECON SUMMARY" not in prompt
    assert "侦察摘要" not in prompt
