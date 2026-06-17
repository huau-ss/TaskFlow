import Flutter
import UIKit

@main
@objc class AppDelegate: FlutterAppDelegate {
    private var documentPickerResult: FlutterResult?
    
    override func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
    ) -> Bool {
        
        let controller = window?.rootViewController as! FlutterViewController
        let documentPickerChannel = FlutterMethodChannel(
            name: "com.taskflow/document_picker",
            binaryMessenger: controller.binaryMessenger
        )
        
        documentPickerChannel.setMethodCallHandler { [weak self] (call, result) in
            if call.method == "pickAudioFile" {
                self?.pickAudioFile(from: controller, result: result)
            } else {
                result(FlutterMethodNotImplemented)
            }
        }
        
        GeneratedPluginRegistrant.register(with: self)
        return super.application(application, didFinishLaunchingWithOptions: launchOptions)
    }
    
    private func pickAudioFile(from viewController: UIViewController, result: @escaping FlutterResult) {
        documentPickerResult = result
        
        let documentPicker: UIDocumentPickerViewController
        
        if #available(iOS 14.0, *) {
            documentPicker = UIDocumentPickerViewController(forOpeningContentTypes: [
                .audio, .mp3, .mpeg4Audio
            ], asCopy: true)
        } else {
            documentPicker = UIDocumentPickerViewController(documentTypes: [
                "public.audio", "public.mp3", "public.mpeg-4-audio", "com.apple.m4a-audio"
            ], in: .import)
        }
        
        documentPicker.allowsMultipleSelection = false
        documentPicker.delegate = self
        documentPicker.presentationController?.delegate = self
        
        viewController.present(documentPicker, animated: true, completion: nil)
    }
}

extension AppDelegate: UIDocumentPickerDelegate {
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let url = urls.first else {
            documentPickerResult?(nil)
            documentPickerResult = nil
            return
        }
        
        documentPickerResult?([
            "path": url.path,
            "name": url.lastPathComponent
        ])
        documentPickerResult = nil
    }
    
    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        documentPickerResult?(nil)
        documentPickerResult = nil
    }
}

extension AppDelegate: UIAdaptivePresentationControllerDelegate {
    func presentationControllerDidDismiss(_ presentationController: UIPresentationController) {
        documentPickerResult?(nil)
        documentPickerResult = nil
    }
}
