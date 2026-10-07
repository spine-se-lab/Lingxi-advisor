"""Opt-in real host acceptance through the shared managed lifecycle."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest
from conftest import PLUGIN_ROOT


_DRIVER = r'''
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {spawnSync}=require('node:child_process');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const core=require(input.kit);
(async()=>{
  const prepared=await core.prepare(input.delivery,input.request);
  const installed=await core.commit(input.delivery,{plan:prepared.plan});
  assert.equal(installed.status,'ok');
  // Reinstall the identical release through the same transaction entry point.
  const repeated=await core.prepare(input.delivery,input.request);
  await core.commit(input.delivery,{plan:repeated.plan});
  if(input.detached)fs.renameSync(input.delivery,input.delivery+'-moved');
  const verify=spawnSync(process.execPath,[path.join(installed.package_ref.root,'bin/codehelix-lingxi-advisor.js'),'protocol','verify'],{
    encoding:'utf8',timeout:240000,input:JSON.stringify({...input.request,managed:repeated.plan.managed})});
  assert.equal(verify.status,0,verify.stdout+verify.stderr);
  const evidence=JSON.parse(verify.stdout).evidence;
  assert.equal(evidence.filter(item=>item.kind==='mcp_server'&&item.status==='connected').length,input.expected_mcp);
  assert(evidence.some(item=>['agent_profile','opencode_config','pi_extension','claude_mcp','deepseek_bundle'].includes(item.kind)));
  fs.mkdirSync(input.data,{recursive:true});
  fs.writeFileSync(path.join(input.data,'keep-user-data.txt'),'preserved');
  const inspected=await core.inspect('lingxi-advisor',{home:input.request.home});
  assert.equal(inspected.observation.registered,true);
  const removal=spawnSync(process.execPath,[path.join(installed.kit_root,'plugin-kit/cli/managed-cli.js'),'remove','lingxi-advisor'],{
    encoding:'utf8',timeout:120000,input:JSON.stringify({home:input.request.home,confirmed:true})});
  assert.equal(removal.status,0,removal.stdout+removal.stderr);
  assert.equal(fs.readFileSync(path.join(input.data,'keep-user-data.txt'),'utf8'),'preserved');
  process.stdout.write(JSON.stringify({status:'ok',evidence,detached:input.detached,data_preserved:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''


def _required_executable(name: str) -> str:
    executable = shutil.which(name)
    assert executable, f'{name} is required for managed lifecycle acceptance'
    return executable


def test_real_host_acceptance_launchers_are_platform_resolved() -> None:
    for name in ('node', 'npm'):
        completed = subprocess.run(
            [_required_executable(name), '--version'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


@pytest.mark.parametrize('profile,agent,host_env', [
    ('icode-chrys-0.28','icode','LINGXI_ADVISOR_REAL_CHRYS'),
    ('opencode-1.x','opencode','LINGXI_ADVISOR_REAL_OPENCODE'),
    ('pi-0.85.1','pi','LINGXI_ADVISOR_REAL_PI'),
    ('claude-code-2.1.285','claude-code','LINGXI_ADVISOR_REAL_CLAUDE'),
    ('deepseek-harness-0.2.0-rc.2','deepseek-harness','LINGXI_ADVISOR_REAL_DSH'),
])
@pytest.mark.parametrize('detached', [False, True])
def test_real_managed_host_lifecycle(profile, agent, host_env, detached, tmp_path) -> None:
    host=os.environ.get(host_env)
    if not host:
        pytest.skip(f'{host_env} is not set')
    node=os.environ.get('LINGXI_ADVISOR_REAL_NODE') or _required_executable('node')
    delivery=PLUGIN_ROOT/'delivery'/profile
    if detached:
        copied=tmp_path/'standalone-delivery'
        shutil.copytree(delivery,copied)
        delivery=copied
        installed=subprocess.run([_required_executable('npm'),'ci','--ignore-scripts','--no-audit','--no-fund'],cwd=delivery,capture_output=True,text=True,timeout=180)
        assert installed.returncode==0, installed.stderr
    repo=PLUGIN_ROOT.parents[1]
    kit=delivery/'kit/plugin-kit/installation/orchestrator.js' if detached else repo/'plugin-kit/installation/orchestrator.js'
    project=Path(host).resolve() if agent=='icode' else tmp_path/'project'
    project.mkdir(exist_ok=True)
    xdg={name:tmp_path/f'xdg-{name.lower()}' for name in ('CONFIG','DATA','CACHE','STATE')}
    # OpenCode discovers its global configuration at XDG_CONFIG_HOME/opencode;
    # OPENCODE_CONFIG_DIR is not a supported relocation interface in 1.18.25.
    config=xdg['CONFIG']/'opencode' if agent=='opencode' else tmp_path/'config'
    data=tmp_path/'user-data'
    environment={**os.environ,'GITHUB_TOKEN':'fixture-host-loading-only'}
    # Model use is a separate explicit real-model acceptance; this test loads servers.
    for name in list(environment):
        if name.startswith(('LINGXI_ADVISOR_MODEL_','LINGXI_ADVISOR_JUDGE_','LINGXI_ADVISOR_GENERATOR_')):
            environment.pop(name)
    for name,root in xdg.items():
        environment[f'XDG_{name}_HOME']=str(root)
    target={'agent_system':agent,'root':str(project),'config_root':str(config)}
    if agent != 'icode':target['executable']=str(Path(host).resolve())
    request={'home':str(tmp_path/'home'),'target':target,'configuration':{'data_root':str(data),'allow_preretrieved_updates':False}}
    driver=tmp_path/'lifecycle.cjs';driver.write_text(_DRIVER)
    runtime_only={'pi','claude-code','deepseek-harness'}
    completed=subprocess.run([node,str(driver)],input=json.dumps({'kit':str(kit),'delivery':str(delivery),'request':request,'data':str(data),'detached':detached,'expected_mcp':1 if agent in runtime_only else 2}),env=environment,cwd=tmp_path,capture_output=True,text=True,timeout=900)
    assert completed.returncode==0, completed.stdout+completed.stderr
    evidence=json.loads(completed.stdout)
    assert evidence['status']=='ok' and evidence['data_preserved']
    (tmp_path/'host-verification.json').write_text(json.dumps(evidence,indent=2))
