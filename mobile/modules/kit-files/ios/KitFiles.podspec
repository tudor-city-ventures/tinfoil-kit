Pod::Spec.new do |s|
  s.name           = 'KitFiles'
  s.version        = '1.0.0'
  s.summary        = "The phone app's downloads, book files and the phone's own AI"
  s.homepage       = 'https://tinfoilkit.com'
  s.license        = 'MIT'
  s.author         = 'Tinfoil Kit'
  s.platforms      = { :ios => '16.4' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.dependency 'ExpoFileSystem'
  s.pod_target_xcconfig = { 'DEFINES_MODULE' => 'YES' }
  # Apple Intelligence's model, on iOS 26 and later only: the app still opens on older iPhones
  s.weak_frameworks = 'FoundationModels'
  s.source_files = '**/*.swift'
end
