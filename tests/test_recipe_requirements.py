import copy
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import complete_quest as C
import transplant as T


class RecipeTests(unittest.TestCase):
    def setUp(self):
        self.recipe = T.load(ROOT / 'references/recipes/BaiShanMiWen.json')
        self.target = {
            'PBZGameSystem': {'CycleCount': 0, 'HasGameTime': 123456,
                              'DateTimeString': '2025.01.01-00.00.00'},
            'Narrative': {'NarrativeSavedQuests': [], 'QuestGameTimes': []},
            'Inventory': {'AccessoryInfos': {}, 'MainWeaponInfos': {}},
            'EventPipeline': {'GlobalTags': [], 'ComponentInfoJson': {},
                              'ComponentsOwnerActorInfo': {}, 'ExecuteNodeGuid': {}},
            'Player': {'Dust': 7654321}, 'MapSubsystem': {'unrelated': True},
        }
        quest_op = next(o for o in T.de_ops(self.recipe['slot_ops']) if o[0] == 'oreplace')
        self.target['Narrative']['NarrativeSavedQuests'] = [copy.deepcopy(quest_op[2])]
        self.target['Narrative']['QuestGameTimes'] = [
            {'QuestClass': quest_op[2]['QuestClass'], 'GameTime': 1}]
        for check in self.recipe['requires']:
            p = T.de_path(check['path'])
            # Keyed quest/branch lists already exist above.
            T.parent(self.target, p)[p[-1]] = copy.deepcopy(check['value'])
        self.target['Narrative']['NarrativeSavedQuests'].append(
            {'QuestClass': '/unrelated', 'QuestCompletion': 'untouched'})
        self.flow = next(k for k in self.target['EventPipeline']['ComponentInfoJson'])
        self.target['EventPipeline']['ComponentInfoJson'][self.flow]['EventTag'].append(
            'quest.幻术琵琶.收集背板')

    def test_repair_preserves_unrelated_state(self):
        original = copy.deepcopy(self.target)
        C.check_requirements(self.target, self.recipe)
        p = T.Patcher(self.target, 'synthetic')
        for op in T.de_ops(self.recipe['slot_ops']):
            p.apply(op)
        for key in ('PBZGameSystem', 'Player', 'MapSubsystem'):
            self.assertEqual(self.target[key], original[key])
        self.assertEqual(self.target['Inventory']['MainWeaponInfos'],
                         original['Inventory']['MainWeaponInfos'])
        quests = self.target['Narrative']['NarrativeSavedQuests']
        self.assertEqual(quests[-1], original['Narrative']['NarrativeSavedQuests'][-1])
        self.assertEqual(quests[0]['QuestCompletion'], 'EQuestCompletion::QC_Succeded')
        branch = next(b for b in quests[0]['QuestBranches'] if b['BranchID'] == 'PBZQuestBranch_4')
        self.assertEqual(branch['BranchType'], 'EBranchType::None')
        tags = self.target['EventPipeline']['ComponentInfoJson'][self.flow]['EventTag']
        self.assertIn('quest.幻术琵琶.收集背板', tags)
        self.assertNotIn('bsmw.剑偶.死亡无任务', tags)
        self.assertIn('bsmw.剑偶.死亡有任务', tags)
        item = self.target['Inventory']['AccessoryInfos']['AC_HeavyAttackDamage']
        self.assertEqual(item['CurrentLevel'], 0)
        self.assertEqual(item['DirtyTime'], original['PBZGameSystem']['DateTimeString'])
        with self.assertRaises(ValueError):
            C.check_requirements(self.target, self.recipe)

    def test_rejects_each_missing_requirement(self):
        for check in self.recipe['requires']:
            with self.subTest(path=check['path']):
                target = copy.deepcopy(self.target)
                p = T.de_path(check['path'])
                T.parent(target, p)[p[-1]] = None
                with self.assertRaises(ValueError):
                    C.check_requirements(target, self.recipe)

    def test_unknown_check_and_legacy_recipe(self):
        with self.assertRaises(ValueError):
            C.check_requirements({}, {'requires': [{'op': 'typo', 'path': ['x'], 'value': 1}]})
        C.check_requirements({}, T.load(ROOT / 'references/recipes/JianXiYiShi.json'))

    def test_existing_upgraded_accessory_is_preserved(self):
        item = {'CurrentLevel': 3, 'AcquiredCycle': 0, 'DirtyTime': '2024.01.01-00.00.00'}
        self.target['Inventory']['AccessoryInfos']['AC_HeavyAttackDamage'] = copy.deepcopy(item)
        C.check_requirements(self.target, self.recipe)
        p = T.Patcher(self.target, 'synthetic')
        for op in T.de_ops(self.recipe['slot_ops']):
            p.apply(op)
        self.assertEqual(self.target['Inventory']['AccessoryInfos']['AC_HeavyAttackDamage'], item)

    def test_cli_preflights_all_targets_before_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            valid, invalid, ach = root/'valid.json', root/'invalid.json', root/'ach.json'
            valid.write_text(json.dumps(self.target), encoding='utf8')
            self.target['PBZGameSystem']['CycleCount'] = 1
            invalid.write_text(json.dumps(self.target), encoding='utf8')
            ach.write_text('{"UnlockedIds":["sentinel"]}', encoding='utf8')
            output = root/'out'
            result = subprocess.run([sys.executable, '-I', str(ROOT/'scripts/complete_quest.py'),
                '--quest', 'BaiShanMiWen', '--target', str(valid), '--target', str(invalid),
                '--ach-target', str(ach), '--out-dir', str(output)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'recipe does not apply', result.stderr)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(ach.read_text()), {'UnlockedIds': ['sentinel']})
            dry = subprocess.run([sys.executable, '-I', str(ROOT/'scripts/complete_quest.py'),
                '--quest', 'BaiShanMiWen', '--target', str(valid), '--out-dir', str(output),
                '--dry-run'], capture_output=True)
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertFalse(output.exists())


class ReviveRecipeTests(unittest.TestCase):
    """BaiShanMiWenRevive.json：复活剑偶并把任务还原为进行中（撤销错误击杀）。"""

    def setUp(self):
        self.recipe = T.load(ROOT / 'references/recipes/BaiShanMiWenRevive.json')
        self.target = {
            'PBZGameSystem': {'CycleCount': 0, 'HasGameTime': 84747,
                              'DateTimeString': '2025.01.01-00.00.00'},
            'Narrative': {'NarrativeSavedQuests': [], 'QuestGameTimes': []},
            'Inventory': {'AccessoryInfos': {}, 'MainWeaponInfos': {}},
            'EventPipeline': {'GlobalTags': [], 'ComponentInfoJson': {},
                              'ComponentsOwnerActorInfo': {}, 'ExecuteNodeGuid': {}},
            'Player': {'Dust': 7654321}, 'MapSubsystem': {'unrelated': True},
        }
        quest_op = next(o for o in T.de_ops(self.recipe['slot_ops']) if o[0] == 'oreplace')
        qc = quest_op[2]['QuestClass']
        self.target['Narrative']['NarrativeSavedQuests'] = [copy.deepcopy(quest_op[2])]
        self.target['Narrative']['QuestGameTimes'] = [{'QuestClass': qc, 'GameTime': 1}]
        for check in self.recipe['requires']:
            p = T.de_path(check['path'])
            T.parent(self.target, p)[p[-1]] = copy.deepcopy(check['value'])
        # 击杀窗口内其余可清除标记 + 无关内容
        btt = 'PBZ_Zhengdaodaying_WP-BP_NPCSpawner_C_UAID_60CF84DCBBBEC5AE02_1706554590'
        tags = self.target['EventPipeline']['GlobalTags']
        tags += ['zddy.毕桃桃.见到肉身', 'bsmw.乌冷霜.出场', 'bsmw.乌冷霜.出场seq播放',
                 'bsmw.乌冷霜.消散', 'bsmw.击杀.乌冷霜', 'quest.幻术琵琶.收集背板']
        self.flow = 'PBZ_Zhengdaodaying_WP-BP_FlowActor_C_UAID_E89C25A754346F6602_1373056726'
        self.target['EventPipeline']['ComponentInfoJson'][self.flow]['EventTag'].append(
            'quest.幻术琵琶.收集背板')
        self.target['EventPipeline']['ComponentsOwnerActorInfo'][btt] = {
            'IdleType': 'Dead', 'RelatedSeqName': '', 'OwnerTransform': {'killed': True}}
        nodes = self.target['EventPipeline']['ExecuteNodeGuid']
        for op in T.de_ops(self.recipe['slot_ops']):
            if op[0] == 'del' and op[1][0] == 'EventPipeline' and op[1][1] == 'ExecuteNodeGuid':
                nodes[op[1][2]] = True
        nodes['unrelated-guid'] = True
        self.target['Narrative']['NarrativeSavedQuests'].append(
            {'QuestClass': '/unrelated', 'QuestCompletion': 'untouched'})

    def test_revive_resets_quest_and_revives_puppet(self):
        original = copy.deepcopy(self.target)
        C.check_requirements(self.target, self.recipe)
        p = T.Patcher(self.target, 'synthetic')
        for op in T.de_ops(self.recipe['slot_ops']):
            p.apply(op)
        for key in ('PBZGameSystem', 'Player', 'MapSubsystem'):
            self.assertEqual(self.target[key], original[key])
        quests = self.target['Narrative']['NarrativeSavedQuests']
        self.assertEqual(quests[-1], original['Narrative']['NarrativeSavedQuests'][-1])
        self.assertEqual(quests[0]['QuestCompletion'], 'EQuestCompletion::QC_Started')
        # 分支 1/2 由配方直接标记完成（游戏引擎 BUG：修复后的存档上阶段 1/2 无法自然推进）
        branches = {b['BranchID']: b['BranchType'] for b in quests[0]['QuestBranches']}
        self.assertEqual(branches['1'], 'EBranchType::BranchCompleted')
        self.assertEqual(branches['2'], 'EBranchType::BranchCompleted')
        self.assertEqual(branches['3'], 'EBranchType::BranchActivating')
        # 全局标签：失败/死亡/乌冷霜/见到肉身 全部清除，无关标签保留
        tags = self.target['EventPipeline']['GlobalTags']
        for op in T.de_ops(self.recipe['slot_ops']):
            if op[0] == 'ldel' and op[1] == ['EventPipeline', 'GlobalTags']:
                self.assertNotIn(op[2], tags)
        self.assertIn('quest.幻术琵琶.收集背板', tags)
        # 组件标签：失败标记清除，无关标签保留
        comp_tags = self.target['EventPipeline']['ComponentInfoJson'][self.flow]['EventTag']
        self.assertNotIn('bsmw.剑偶.死亡无任务', comp_tags)
        self.assertIn('quest.幻术琵琶.收集背板', comp_tags)
        # 毕桃桃 NPC 复原
        btt = self.target['EventPipeline']['ComponentsOwnerActorInfo'][
            'PBZ_Zhengdaodaying_WP-BP_NPCSpawner_C_UAID_60CF84DCBBBEC5AE02_1706554590']
        self.assertEqual(btt['IdleType'], 'Crouch')
        self.assertNotIn('killed', btt['OwnerTransform'])
        # 流程节点全部清除，无关节点保留
        nodes = self.target['EventPipeline']['ExecuteNodeGuid']
        self.assertEqual(list(nodes), ['unrelated-guid'])
        # 任务时间按脚本约定改为目标存档当前游戏时长
        self.assertEqual(self.target['Narrative']['QuestGameTimes'][0]['GameTime'], 84747)
        # 已复活的状态不再满足"失败态"前置条件（防重复应用）
        with self.assertRaises(ValueError):
            C.check_requirements(self.target, self.recipe)

    def test_rejects_each_missing_requirement(self):
        for check in self.recipe['requires']:
            with self.subTest(path=check['path']):
                target = copy.deepcopy(self.target)
                p = T.de_path(check['path'])
                T.parent(target, p)[p[-1]] = None
                with self.assertRaises(ValueError):
                    C.check_requirements(target, self.recipe)


if __name__ == '__main__':
    unittest.main()
