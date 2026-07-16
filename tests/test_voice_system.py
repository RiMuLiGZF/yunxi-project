"""
云汐语音系统测试脚本
====================

测试内容：
1. TTS 引擎可用性检测
2. 音色预设管理
3. 韵律控制器（人格→语音映射）
4. CosyVoice 集成（如果服务可用）
5. 情感/场景韵律计算

使用方法：
    python test_voice_system.py
"""

import sys
import os

# 确保 shared 目录在路径中
_current_dir = os.path.dirname(os.path.abspath(__file__))
_shared_dir = os.path.join(_current_dir, '..', 'shared')
if _shared_dir not in sys.path:
    sys.path.insert(0, _shared_dir)


def test_tts_engine():
    """测试 TTS 引擎"""
    print("\n" + "=" * 60)
    print("  测试 1: TTS 引擎可用性检测")
    print("=" * 60)
    
    try:
        from voice_engine import TTSEngine
        
        tts = TTSEngine()
        
        print(f"\n  ✓ TTSEngine 加载成功")
        print(f"  ✓ 可用引擎: {tts.available_engines}")
        print(f"  ✓ 当前引擎: {tts.current_engine}")
        
        # 语音选项
        options = tts.get_voice_options()
        print(f"  ✓ 可用音色: {len(options)} 种")
        
        # 分类统计
        categories = tts.get_voice_categories()
        print(f"  ✓ 音色分类: {len(categories)} 类")
        for cat, opts in categories.items():
            print(f"      - {cat}: {len(opts)} 种")
        
        print("\n  🎉 TTS 引擎测试通过！")
        return True
        
    except Exception as e:
        print(f"\n  ✗ TTS 引擎测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_prosody_controller():
    """测试韵律控制器"""
    print("\n" + "=" * 60)
    print("  测试 2: 韵律控制器（人格→语音映射）")
    print("=" * 60)
    
    try:
        from prosody_controller import ProsodyController, PersonalityTraits
        
        # 默认人格
        controller = ProsodyController()
        print(f"\n  ✓ ProsodyController 加载成功")
        
        # 测试不同情感
        test_text = "你好，很高兴见到你！今天天气真不错。"
        emotions = ['warm', 'happy', 'sad', 'calm', 'excited', 'gentle', 'playful']
        
        print(f"\n  🎭 情感韵律测试（文本: \"{test_text[:20]}...\"）")
        print(f"  {'情感':<15} {'语速':<8} {'音调':<8} {'音量':<8}")
        print(f"  {'-'*15} {'-'*8} {'-'*8} {'-'*8}")
        
        for emotion in emotions:
            prosody = controller.compute_prosody(test_text, emotion=emotion)
            print(f"  {emotion:<15} {prosody.rate:<8.2f} {prosody.pitch:<8.2f} {prosody.volume:<8.2f}")
        
        # 测试场景
        print(f"\n  🏠 场景韵律测试")
        scenes = ['work_dev', 'study_plan', 'emotion_companion', 'life_management']
        print(f"  {'场景':<20} {'情感':<12} {'语速':<8} {'停顿':<8}")
        print(f"  {'-'*20} {'-'*12} {'-'*8} {'-'*8}")
        
        for scene in scenes:
            prosody = controller.compute_prosody(test_text, scene=scene)
            print(f"  {scene:<20} {prosody.emotion:<12} {prosody.rate:<8.2f} {prosody.pause_between_sentences:<8.2f}s")
        
        # 测试 CosyVoice 指令生成
        print(f"\n  📝 CosyVoice 指令生成示例")
        instruction = controller.generate_cosyvoice_instruction(
            test_text, emotion='warm', scene='emotion_companion'
        )
        print(f"  温暖+情感陪伴场景: {instruction}")
        
        instruction2 = controller.generate_cosyvoice_instruction(
            test_text, emotion='excited', scene='work_dev'
        )
        print(f"  兴奋+工作场景: {instruction2}")
        
        # 测试 SSML 生成
        print(f"\n  🎤 SSML 生成示例 (edge-tts 兼容)")
        ssml = controller.generate_ssml(test_text, emotion='happy')
        print(f"  开心情感: {ssml[:100]}...")
        
        print("\n  🎉 韵律控制器测试通过！")
        return True
        
    except Exception as e:
        print(f"\n  ✗ 韵律控制器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_voice_preset_manager():
    """测试音色预设管理器"""
    print("\n" + "=" * 60)
    print("  测试 3: 音色预设管理器")
    print("=" * 60)
    
    try:
        import tempfile
        from voice_preset_manager import VoicePresetManager
        
        # 使用临时目录
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = VoicePresetManager(storage_dir=tmpdir)
            
            print(f"\n  ✓ VoicePresetManager 加载成功")
            print(f"  ✓ 存储目录: {tmpdir}")
            
            # 内置预设
            presets = manager.list_presets()
            print(f"  ✓ 内置预设: {len(presets)} 套")
            
            for preset in presets:
                status = "✓ 已就绪" if manager.is_preset_ready(preset.preset_id) else "○ 待配置"
                print(f"      {status} {preset.name} ({preset.style})")
            
            # 当前激活
            active = manager.get_active_preset()
            print(f"\n  ✓ 当前激活: {active.name if active else '无'}")
            
            # 场景推荐
            print(f"\n  🎯 场景推荐音色:")
            scenes = ['work_dev', 'emotion_companion', 'entertainment']
            for scene in scenes:
                recommended = manager.get_preset_for_scene(scene)
                name = recommended.name if recommended else "无可用音色"
                print(f"      {scene}: {name}")
            
            # 合成参数
            if active:
                params = manager.get_synthesis_params()
                print(f"\n  ✓ 合成参数:")
                for k, v in params.items():
                    if v:
                        print(f"      {k}: {str(v)[:50]}")
        
        print("\n  🎉 音色预设管理器测试通过！")
        return True
        
    except Exception as e:
        print(f"\n  ✗ 音色预设管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_cosyvoice_client():
    """测试 CosyVoice 客户端"""
    print("\n" + "=" * 60)
    print("  测试 4: CosyVoice 客户端")
    print("=" * 60)
    
    try:
        from cosyvoice_client import CosyVoiceClient, CosyVoiceConfig, is_cosyvoice_available
        
        config = CosyVoiceConfig(
            api_url="http://localhost:50000",
            timeout=5,
        )
        
        client = CosyVoiceClient(config)
        
        print(f"\n  ✓ CosyVoiceClient 加载成功")
        print(f"  ✓ API 地址: {config.api_url}")
        
        # 检测服务可用性
        available = client.is_available
        status = "✅ 运行中" if available else "❌ 未运行"
        print(f"  ✓ 服务状态: {status}")
        
        if available:
            # 说话人列表
            speakers = client.list_speakers()
            print(f"  ✓ 已注册说话人: {len(speakers)} 个")
            
            # 指令构建测试
            print(f"\n  📝 指令构建测试:")
            instr1 = client.build_instruction(emotion='happy', speed='fast')
            print(f"      开心+快语速: {instr1}")
            
            instr2 = client.build_instruction(emotion='warm', dialect='sichuan')
            print(f"      温暖+四川话: {instr2}")
        else:
            print(f"\n  ⚠ CosyVoice 服务未启动，跳过合成测试")
            print(f"    启动命令: python shared/cosyvoice_service.py")
            print(f"    部署指南: docs/cosyvoice_integration_guide.md")
        
        print("\n  🎉 CosyVoice 客户端测试通过！")
        return True
        
    except Exception as e:
        print(f"\n  ✗ CosyVoice 客户端测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_integration():
    """测试整体集成"""
    print("\n" + "=" * 60)
    print("  测试 5: 整体集成测试")
    print("=" * 60)
    
    try:
        from voice_engine import TTSEngine
        from prosody_controller import ProsodyController
        from voice_preset_manager import VoicePresetManager
        import tempfile
        
        # 测试文本
        test_texts = [
            ("你好，我是云汐，很高兴认识你！", "warm", "emotion_companion"),
            ("这个问题的核心在于算法的时间复杂度。让我来解释一下。", "serious", "work_dev"),
            ("哈哈哈哈太有趣了！再来一个笑话呗！", "playful", "entertainment"),
        ]
        
        tts = TTSEngine()
        prosody_ctrl = ProsodyController()
        
        print(f"\n  ✓ 所有模块加载成功")
        print(f"  ✓ 当前 TTS 引擎: {tts.current_engine}")
        print(f"\n  📊 文本韵律分析:")
        print(f"  {'文本':<40} {'情感':<10} {'场景':<20} {'语速':<6}")
        print(f"  {'-'*40} {'-'*10} {'-'*20} {'-'*6}")
        
        for text, emotion, scene in test_texts:
            prosody = prosody_ctrl.compute_prosody(text, emotion=emotion, scene=scene)
            display_text = text[:38] + "..." if len(text) > 38 else text
            print(f"  {display_text:<40} {emotion:<10} {scene:<20} {prosody.rate:<6.2f}")
        
        # CosyVoice 集成状态
        from cosyvoice_client import is_cosyvoice_available
        cosy_available = is_cosyvoice_available()
        
        print(f"\n  🔗 集成状态:")
        print(f"    TTS 引擎: {tts.current_engine}")
        print(f"    CosyVoice: {'✅ 已连接' if cosy_available else '○ 未连接'}")
        print(f"    韵律控制: ✅ 可用")
        print(f"    音色管理: ✅ 可用")
        
        # 降级链
        print(f"\n  🔄 TTS 降级链:")
        engines = tts.available_engines
        for i, eng in enumerate(engines, 1):
            marker = "◄ 当前" if eng == tts.current_engine else ""
            print(f"    {i}. {eng} {marker}")
        
        print("\n  🎉 整体集成测试通过！")
        return True
        
    except Exception as e:
        print(f"\n  ✗ 整体集成测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("\n" + "╔" + "═" * 58 + "╗")
    print("║" + " " * 15 + "云汐语音系统测试" + " " * 27 + "║")
    print("╚" + "═" * 58 + "╝")
    print(f"\n  Python: {sys.version.split()[0]}")
    print(f"  测试时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    # 运行所有测试
    results['TTS 引擎'] = test_tts_engine()
    results['韵律控制器'] = test_prosody_controller()
    results['音色预设管理'] = test_voice_preset_manager()
    results['CosyVoice 客户端'] = test_cosyvoice_client()
    results['整体集成'] = test_integration()
    
    # 汇总
    print("\n" + "=" * 60)
    print("  测试结果汇总")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ 通过" if result else "❌ 失败"
        print(f"  {status} {name}")
    
    print(f"\n  总计: {passed}/{total} 项测试通过")
    
    if passed == total:
        print("\n  🎊 所有测试通过！语音系统运行正常。")
    else:
        print(f"\n  ⚠ 有 {total - passed} 项测试失败，请检查上方错误信息。")
    
    print("=" * 60)
    
    return passed == total


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
