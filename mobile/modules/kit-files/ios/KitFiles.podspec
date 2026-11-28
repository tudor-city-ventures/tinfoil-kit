Pod::Spec.new do |s|
  s.name           = 'KitFiles'
  s.version        = '1.0.0'
  s.summary        = "The phone app's book files: kept out of backups, and checked"
  s.homepage       = 'https://tinfoilkit.com'
  s.license        = 'MIT'
  s.author         = 'Tinfoil Kit'
  s.platforms      = { :ios => '16.4' }
  s.source         = { git: '' }
  s.static_framework = true
  s.dependency 'ExpoModulesCore'
  s.pod_target_xcconfig = { 'DEFINES_MODULE' => 'YES' }
  s.source_files = '**/*.swift'
end
