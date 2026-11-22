// Tinfoil Kit's Mac app. Double-click it to set the kit up, and after that to open it. Apple notarizes it, so macOS
// opens it with no trip to System Settings, which a downloaded script needs. It carries a copy of the kit for the
// first setup; SETUP and ./kit update keep the kit current after that, and SETUP gets a Mac its own Python.
// The windows are here; the file work is in app.sh. mac/build.sh builds it.
#import <Cocoa/Cocoa.h>
#include <signal.h>
#include <stdio.h>

static NSString *line(NSString *s) { return [s stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet]; }
// Caught rather than ignored, so the launcher this app starts can still be stopped with SIGTERM (an ignored signal
// stays ignored in child processes); the dispatch source below hears it either way.
static void heard(int sig) { (void)sig; }

@interface App : NSObject <NSApplicationDelegate, NSWindowDelegate>
@end

@implementation App {
  NSString *script;                 // app.sh
  NSArray<NSString *> *answers;     // KIT_APP_ANSWERS: the buttons a test presses, in order, numbered from 1
  NSUInteger answered;
  NSString *kit, *where, *url;      // the kit this window opened, where it is, and its page
  NSTask *task;                     // the kit's launcher, tools/launch.sh
  BOOL libraryUp, quitting;
  NSMutableData *pending;           // the launcher's output that isn't a whole line yet
  NSWindow *window;
  NSTextField *headline, *detail;
  NSTextView *output;
  NSButton *browser;
  dispatch_source_t sigterm;
}

#pragma mark - Asking

// The button the person pressed, from 0. A test's answers stand in for the person, and the question goes to its log.
- (NSInteger)ask:(NSString *)title text:(NSString *)text buttons:(NSArray<NSString *> *)buttons {
  if (answers) {
    NSInteger pick = answered < answers.count ? answers[answered].integerValue - 1 : (NSInteger)buttons.count - 1;
    answered++;
    printf("ASK: %s | %s | %s -> %s\n", title.UTF8String, [text stringByReplacingOccurrencesOfString:@"\n" withString:@" "].UTF8String,
           [buttons componentsJoinedByString:@" / "].UTF8String, pick >= 0 && pick < (NSInteger)buttons.count ?
           buttons[pick].UTF8String : "?");
    fflush(stdout);
    return pick;
  }
  NSAlert *alert = [NSAlert new];
  alert.messageText = title;
  alert.informativeText = text;
  for (NSString *b in buttons) [alert addButtonWithTitle:b];
  [NSApp activateIgnoringOtherApps:YES];
  return [alert runModal] - NSAlertFirstButtonReturn;
}

// app.sh with these arguments; returns what it printed.
- (NSString *)run:(NSArray<NSString *> *)args {
  NSTask *t = [NSTask new];
  t.executableURL = [NSURL fileURLWithPath:@"/bin/bash"];
  t.arguments = [@[script] arrayByAddingObjectsFromArray:args];
  NSPipe *pipe = [NSPipe pipe];
  t.standardOutput = pipe;
  t.standardInput = [NSFileHandle fileHandleWithNullDevice];
  if (![t launchAndReturnError:nil]) return @"";
  NSData *data = [pipe.fileHandleForReading readDataToEndOfFile];
  [t waitUntilExit];
  NSString *out = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding] ?: @"";
  if (answers) printf("RAN: app.sh %s\n%s", [args componentsJoinedByString:@" "].UTF8String, out.UTF8String);
  return out;
}

#pragma mark - Starting

- (void)applicationDidFinishLaunching:(NSNotification *)note {
  [self menus];
  script = [NSBundle.mainBundle pathForResource:@"app" ofType:@"sh"];
  NSString *a = NSProcessInfo.processInfo.environment[@"KIT_APP_ANSWERS"];
  if (a) answers = [a componentsSeparatedByString:@","];
  // Quit properly on SIGTERM too (a test, kill), so the kit's servers stop with the app.
  signal(SIGTERM, heard);
  sigterm = dispatch_source_create(DISPATCH_SOURCE_TYPE_SIGNAL, SIGTERM, 0, dispatch_get_main_queue());
  dispatch_source_set_event_handler(sigterm, ^{ [NSApp terminate:nil]; });
  dispatch_resume(sigterm);
  [NSApp activateIgnoringOtherApps:YES];
  if (![self moved]) [self start];
}

// Opened from Downloads or the disk image it came in: offer to move it to Applications, where the person will look
// for it in an outage. Returns YES when the copy there is starting instead.
- (BOOL)moved {
  NSString *path = NSBundle.mainBundle.bundlePath;
  NSNumber *readOnly = nil;
  [[NSURL fileURLWithPath:path] getResourceValue:&readOnly forKey:NSURLVolumeIsReadOnlyKey error:nil];
  BOOL downloaded = [path containsString:@"/AppTranslocation/"] || readOnly.boolValue ||
                    [path hasPrefix:[NSHomeDirectory() stringByAppendingString:@"/Downloads/"]];
  if (!downloaded || [self ask:@"Move Tinfoil Kit to your Applications folder?"
                          text:@"Then it's in Launchpad and Spotlight, ready for when the internet is down."
                       buttons:@[@"Move to Applications", @"Not Now"]] != 0) return NO;
  NSString *dest = line([self run:@[@"move", path]]);
  if (!dest.length) {
    [self ask:@"Tinfoil Kit couldn't move itself" text:@"Drag it to the Applications folder in Finder instead. For now it carries on from here."
      buttons:@[@"OK"]];
    return NO;
  }
  [NSTask launchedTaskWithExecutableURL:[NSURL fileURLWithPath:@"/usr/bin/open"] arguments:@[@"-n", dest] error:nil terminationHandler:nil];
  [NSApp terminate:nil];
  return YES;
}

// Find the kit and open it, or set one up.
- (void)start {
  NSMutableArray<NSArray<NSString *> *> *kits = [NSMutableArray array], *unplugged = [NSMutableArray array];
  for (NSString *l in [[self run:@[@"find"]] componentsSeparatedByString:@"\n"]) {
    NSArray<NSString *> *f = [l componentsSeparatedByString:@"\t"];    // status, folder, where
    if (f.count != 3) continue;
    if ([f[0] isEqual:@"unplugged"]) [unplugged addObject:f];
    else if ([f[0] isEqual:@"ready"]) [kits insertObject:f atIndex:0];
    else [kits addObject:f];
  }
  NSArray<NSString *> *k = kits.firstObject;
  if (kits.count > 1) {
    NSMutableArray<NSString *> *names = [NSMutableArray array];
    for (NSArray<NSString *> *f in kits)
      [names addObject:[NSString stringWithFormat:@"On %@%@", f[2], [f[0] isEqual:@"ready"] ? @"" : @" (not set up yet)"]];
    [names addObject:@"Cancel"];
    NSInteger pick = [self ask:@"Which Tinfoil Kit?" text:@"There's one in more than one place." buttons:names];
    if (pick < 0 || pick >= (NSInteger)kits.count) { [self quit]; return; }
    k = kits[pick];
  }
  if (k && [k[0] isEqual:@"ready"]) { [self open:k]; return; }
  if (k) {
    if ([self ask:@"Finish setting up Tinfoil Kit?"
             text:[NSString stringWithFormat:@"The kit on %@ isn't set up yet. Setup carries on where it stopped, in a Terminal window.", k[2]]
          buttons:@[@"Continue Setup", @"Cancel"]] == 0)
      [self run:@[@"setup", k[1]]];
    [self quit];
    return;
  }
  if (unplugged.count) {
    NSString *drive = [unplugged[0][2] substringFromIndex:@"the drive ".length];
    NSInteger pick = [self ask:[NSString stringWithFormat:@"Plug in the drive %@", drive]
                          text:[NSString stringWithFormat:@"Your Tinfoil Kit is on the drive %@. Plug it in, give it a few seconds, then click Look Again.", drive]
                       buttons:@[@"Look Again", @"Set Up a New Kit", @"Quit"]];
    if (pick == 0) { [self start]; return; }
    if (pick != 1) { [self quit]; return; }
  }
  NSString *text = @"Setup asks a few questions in a Terminal window: where you live, and whether the kit goes on an external drive or on this Mac. "
                   @"Then it downloads an offline AI, library and maps, which takes hours. Keep your Mac plugged in.";
  if (!unplugged.count) text = [text stringByAppendingString:@"\n\nAlready set one up on a drive? Plug it in, then open Tinfoil Kit again."];
  if ([self ask:@"Set up Tinfoil Kit" text:text buttons:@[@"Set Up", @"Cancel"]] == 0)
    [self run:@[@"setup"]];
  [self quit];
}

- (void)quit { [NSApp terminate:nil]; }

#pragma mark - The kit's window

- (void)open:(NSArray<NSString *> *)k {
  kit = k[1];
  where = k[2];
  [self run:@[@"remember", kit]];
  [self makeWindow];
  pending = [NSMutableData data];
  task = [NSTask new];
  task.executableURL = [NSURL fileURLWithPath:@"/bin/bash"];
  task.arguments = @[[kit stringByAppendingPathComponent:@"tools/launch.sh"]];
  task.currentDirectoryURL = [NSURL fileURLWithPath:kit];
  task.standardInput = [NSFileHandle fileHandleWithNullDevice];
  NSPipe *pipe = [NSPipe pipe];
  task.standardOutput = pipe;
  task.standardError = pipe;
  __weak App *me = self;
  pipe.fileHandleForReading.readabilityHandler = ^(NSFileHandle *h) {
    NSData *d = h.availableData;
    if (!d.length) h.readabilityHandler = nil;
    dispatch_async(dispatch_get_main_queue(), ^{ [me took:d]; });
  };
  task.terminationHandler = ^(NSTask *t) { dispatch_async(dispatch_get_main_queue(), ^{ [me ended]; }); };
  NSError *error = nil;
  if (![task launchAndReturnError:&error]) {
    task = nil;
    [self say:@"Tinfoil Kit couldn't start" detail:error.localizedDescription];
  }
}

- (NSTextField *)label:(NSRect)frame size:(CGFloat)size bold:(BOOL)bold {
  NSTextField *t = [NSTextField wrappingLabelWithString:@""];
  t.frame = frame;
  t.font = bold ? [NSFont boldSystemFontOfSize:size] : [NSFont systemFontOfSize:size];
  [window.contentView addSubview:t];
  return t;
}

- (NSButton *)button:(NSString *)title x:(CGFloat)x width:(CGFloat)w action:(SEL)action {
  NSButton *b = [NSButton buttonWithTitle:title target:self action:action];
  b.frame = NSMakeRect(x, 14, w, 32);
  [window.contentView addSubview:b];
  return b;
}

- (void)makeWindow {
  window = [[NSWindow alloc] initWithContentRect:NSMakeRect(0, 0, 580, 400)
                                       styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable
                                         backing:NSBackingStoreBuffered defer:NO];
  window.title = @"Tinfoil Kit";
  window.delegate = self;
  window.releasedWhenClosed = NO;
  NSImageView *icon = [NSImageView imageViewWithImage:NSApp.applicationIconImage];
  icon.frame = NSMakeRect(20, 316, 64, 64);
  [window.contentView addSubview:icon];
  headline = [self label:NSMakeRect(100, 348, 460, 26) size:18 bold:YES];
  detail = [self label:NSMakeRect(100, 296, 460, 48) size:13 bold:NO];
  NSScrollView *scroll = [NSTextView scrollableTextView];
  scroll.frame = NSMakeRect(20, 60, 540, 224);
  scroll.borderType = NSBezelBorder;
  output = scroll.documentView;
  output.editable = NO;
  output.font = [NSFont monospacedSystemFontOfSize:11 weight:NSFontWeightRegular];
  output.textColor = NSColor.textColor;
  output.backgroundColor = NSColor.textBackgroundColor;
  output.textContainerInset = NSMakeSize(4, 6);
  [window.contentView addSubview:scroll];
  [self button:@"Update…" x:14 width:110 action:@selector(update:)];
  [self button:@"Remove…" x:124 width:110 action:@selector(remove:)];
  browser = [self button:@"Open in Browser" x:404 width:162 action:@selector(openBrowser:)];
  browser.keyEquivalent = @"\r";
  browser.enabled = NO;
  [self say:@"Starting Tinfoil Kit…"
     detail:[NSString stringWithFormat:@"It's on %@. The page opens in your browser in a moment; the AI can take a minute to load.", where]];
  [window center];
  [window makeKeyAndOrderFront:nil];
  [NSApp activateIgnoringOtherApps:YES];
}

- (void)say:(NSString *)title detail:(NSString *)text {
  headline.stringValue = title;
  detail.stringValue = text ?: @"";
}

// The launcher's output, a line at a time: into the window, and its "Open:" line says the page is up.
- (void)took:(NSData *)data {
  [pending appendData:data];
  const char *bytes = pending.bytes;
  NSUInteger start = 0;
  for (NSUInteger i = 0; i < pending.length; i++) {
    if (bytes[i] != '\n') continue;
    NSData *one = [pending subdataWithRange:NSMakeRange(start, i - start)];
    start = i + 1;
    NSString *l = [[NSString alloc] initWithData:one encoding:NSUTF8StringEncoding] ?:
                  [[NSString alloc] initWithData:one encoding:NSISOLatin1StringEncoding];
    [self show:l];
  }
  [pending replaceBytesInRange:NSMakeRange(0, start) withBytes:NULL length:0];
}

- (void)show:(NSString *)l {
  if (answers) { printf("KIT: %s\n", l.UTF8String); fflush(stdout); }
  if ([l containsString:@"Ctrl-C"]) return;    // (said for a Terminal window; this window's own text says it)
  NSDictionary *style = @{NSFontAttributeName: output.font, NSForegroundColorAttributeName: NSColor.textColor};
  [output.textStorage appendAttributedString:[[NSAttributedString alloc] initWithString:[l stringByAppendingString:@"\n"] attributes:style]];
  [output scrollToEndOfDocument:nil];
  if ([l containsString:@"Library:  ready"]) libraryUp = YES;
  NSRange r = [l rangeOfString:@"Open:"];
  if (r.location == NSNotFound) return;
  url = line([l substringFromIndex:NSMaxRange(r)]);
  browser.enabled = YES;
  if (libraryUp)
    [self say:@"Tinfoil Kit is open in your browser"
       detail:[NSString stringWithFormat:@"It's on %@. Keep this window open while you use it: closing it stops the kit.", where]];
  else
    [self say:@"Tinfoil Kit didn't start properly"
       detail:@"The messages below say what's missing. Clicking Update while you're online gets it."];
}

- (void)ended {
  task = nil;
  if (quitting) return;
  browser.enabled = NO;
  [self say:@"Tinfoil Kit stopped" detail:@"The messages below say why. Close this window and open Tinfoil Kit to try again."];
}

// Stop the launcher, which stops the servers it started.
- (void)stopKit {
  if (!task.running) return;
  quitting = YES;
  [task terminate];
  NSDate *deadline = [NSDate dateWithTimeIntervalSinceNow:5];
  while (task.running && deadline.timeIntervalSinceNow > 0)
    [NSRunLoop.currentRunLoop runMode:NSDefaultRunLoopMode beforeDate:[NSDate dateWithTimeIntervalSinceNow:0.1]];
  if (task.running) kill(task.processIdentifier, SIGKILL);
}

- (void)openBrowser:(id)sender {
  if (url) [NSWorkspace.sharedWorkspace openURL:[NSURL URLWithString:url]];
}

- (void)update:(id)sender {
  if ([self ask:@"Update Tinfoil Kit?"
           text:@"This stops the kit. Then, in a Terminal window, setup gets the newest AI models, books and maps, and only what changed. You need to be online."
        buttons:@[@"Update", @"Cancel"]] != 0) return;
  [self stopKit];
  [self run:@[@"update", kit]];
  [self quit];
}

- (void)remove:(id)sender {
  if ([self ask:@"Remove Tinfoil Kit?"
           text:[NSString stringWithFormat:@"This stops the kit and opens the uninstaller in a Terminal window. It says what it will delete from %@ and asks before it does. "
                 @"To remove this app too, drag it from Applications to the Trash afterwards.", where]
        buttons:@[@"Continue", @"Cancel"]] != 0) return;
  [self stopKit];
  [self run:@[@"remove", kit]];
  [self quit];
}

#pragma mark - The app

- (void)windowWillClose:(NSNotification *)note { [self quit]; }

- (void)applicationWillTerminate:(NSNotification *)note { [self stopKit]; }

// Clicking the app in the Dock brings the page back.
- (BOOL)applicationShouldHandleReopen:(NSApplication *)app hasVisibleWindows:(BOOL)visible {
  [window makeKeyAndOrderFront:nil];
  [self openBrowser:nil];
  return YES;
}

- (void)menus {
  NSMenu *bar = [NSMenu new], *appMenu = [NSMenu new], *edit = [[NSMenu alloc] initWithTitle:@"Edit"],
         *win = [[NSMenu alloc] initWithTitle:@"Window"];
  for (NSMenu *m in @[appMenu, edit, win]) [bar addItemWithTitle:@"" action:nil keyEquivalent:@""].submenu = m;
  [appMenu addItemWithTitle:@"About Tinfoil Kit" action:@selector(orderFrontStandardAboutPanel:) keyEquivalent:@""];
  [appMenu addItem:NSMenuItem.separatorItem];
  [appMenu addItemWithTitle:@"Hide Tinfoil Kit" action:@selector(hide:) keyEquivalent:@"h"];
  [appMenu addItemWithTitle:@"Quit Tinfoil Kit" action:@selector(terminate:) keyEquivalent:@"q"];
  [edit addItemWithTitle:@"Copy" action:@selector(copy:) keyEquivalent:@"c"];
  [edit addItemWithTitle:@"Select All" action:@selector(selectAll:) keyEquivalent:@"a"];
  [win addItemWithTitle:@"Minimize" action:@selector(performMiniaturize:) keyEquivalent:@"m"];
  [win addItemWithTitle:@"Close" action:@selector(performClose:) keyEquivalent:@"w"];
  NSApp.mainMenu = bar;
  NSApp.windowsMenu = win;
}

@end

int main(void) {
  @autoreleasepool {
    static App *app;    // NSApplication holds its delegate weakly
    app = [App new];
    NSApplication.sharedApplication.delegate = app;
    [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];
    [NSApp run];
  }
  return 0;
}
