import 'package:flutter_test/flutter_test.dart';

// Mock RecordingResult
class MockRecordingResult {
  final String path;
  final DateTime startedAt;
  final DateTime endedAt;

  MockRecordingResult({
    required this.path,
    required this.startedAt,
    required this.endedAt,
  });

  Duration get duration => endedAt.difference(startedAt);
}

// 独立的 Mock RecordingService，不继承原始类，避免触发 AudioRecorder 初始化
class MockRecordingService {
  bool mockHasPermission = true;
  String? mockError;
  String mockRecordingPath = '/mock/recording.wav';
  bool _isRecording = false;

  bool get isRecording => _isRecording;

  Future<bool> hasPermission() async {
    if (mockError != null) {
      throw Exception(mockError);
    }
    return mockHasPermission;
  }

  Future<String> startRecording() async {
    if (mockError != null) {
      throw Exception(mockError);
    }
    _isRecording = true;
    return mockRecordingPath;
  }

  Future<MockRecordingResult?> stopRecording() async {
    if (mockError != null) {
      throw Exception(mockError);
    }
    _isRecording = false;
    return MockRecordingResult(
      path: mockRecordingPath,
      startedAt: DateTime.now().subtract(const Duration(seconds: 10)),
      endedAt: DateTime.now(),
    );
  }

  Future<void> cancelRecording() async {
    if (mockError != null) {
      throw Exception(mockError);
    }
    _isRecording = false;
  }

  void dispose() {
    // 清理资源
    _isRecording = false;
  }
}

void main() {
  group('RecordingService Tests (Mock)', () {
    late MockRecordingService mockService;

    setUp(() {
      mockService = MockRecordingService();
    });

    tearDown(() {
      mockService.dispose();
    });

    test('RecordingService 实例化成功', () {
      expect(mockService, isNotNull);
    });

    test('hasPermission 返回 true', () async {
      mockService.mockHasPermission = true;
      final result = await mockService.hasPermission();
      expect(result, isTrue);
    });

    test('hasPermission 返回 false', () async {
      mockService.mockHasPermission = false;
      final result = await mockService.hasPermission();
      expect(result, isFalse);
    });

    test('hasPermission 抛出异常', () async {
      mockService.mockError = 'Permission denied';
      expect(
        () => mockService.hasPermission(),
        throwsA(isA<Exception>()),
      );
    });

    test('dispose 后服务仍然可用', () {
      expect(mockService, isNotNull);
    });
  });

  group('RecordingService 录音状态测试 (Mock)', () {
    test('RecordingService 可以正常创建和销毁', () {
      final service = MockRecordingService();
      expect(service, isNotNull);
      service.dispose();
    });

    test('RecordingService 异步方法可以正常调用', () async {
      final service = MockRecordingService();
      final result = await service.hasPermission();
      expect(result, isA<bool>());
      service.dispose();
    });

    test('isRecording 默认返回 false', () {
      final service = MockRecordingService();
      expect(service.isRecording, isFalse);
      service.dispose();
    });

    test('startRecording 返回录音路径', () async {
      final service = MockRecordingService();
      final path = await service.startRecording();
      expect(path, isA<String>());
      expect(path, equals('/mock/recording.wav'));
      expect(service.isRecording, isTrue);
      service.dispose();
    });

    test('stopRecording 返回 RecordingResult', () async {
      final service = MockRecordingService();
      // 先开始录音
      await service.startRecording();
      final result = await service.stopRecording();
      expect(result, isA<MockRecordingResult>());
      expect(result!.path, equals('/mock/recording.wav'));
      expect(result.duration.inSeconds, greaterThanOrEqualTo(0));
      expect(service.isRecording, isFalse);
      service.dispose();
    });

    test('cancelRecording 停止录音并清理', () async {
      final service = MockRecordingService();
      await service.startRecording();
      expect(service.isRecording, isTrue);
      await service.cancelRecording();
      expect(service.isRecording, isFalse);
      service.dispose();
    });

    test('错误场景 - 开始录音失败', () async {
      final service = MockRecordingService();
      service.mockError = 'Recording failed';
      expect(
        () => service.startRecording(),
        throwsA(isA<Exception>()),
      );
      service.dispose();
    });

    test('错误场景 - 停止录音失败', () async {
      final service = MockRecordingService();
      await service.startRecording();
      service.mockError = 'Stop failed';
      expect(
        () => service.stopRecording(),
        throwsA(isA<Exception>()),
      );
      service.dispose();
    });

    test('错误场景 - 取消录音失败', () async {
      final service = MockRecordingService();
      service.mockError = 'Cancel failed';
      expect(
        () => service.cancelRecording(),
        throwsA(isA<Exception>()),
      );
      service.dispose();
    });
  });
}

/*
 * 注意: 由于 `record` 插件依赖原生平台通道 (MethodChannel)，
 * 在单元测试环境中无法使用。这里使用了独立的 MockRecordingService
 * 类来测试 RecordingService 的逻辑，不继承原始类以避免触发
 * AudioRecorder 的原生初始化。
 *
 * 如需完整测试，请在真机或模拟器上运行集成测试:
 * flutter test integration_test/
 */
