#import <Foundation/Foundation.h>

NS_ASSUME_NONNULL_BEGIN

/// Runs `block` and turns any Objective-C exception it raises into an NSError,
/// so Swift can recover from AVFoundation calls (notably AVAudioEngine's
/// installTapOnBus:) that abort the process via NSException rather than a
/// catchable Swift error. Returns nil when the block completes normally.
NSError *_Nullable ObjCTryCatch(void (NS_NOESCAPE ^block)(void));

NS_ASSUME_NONNULL_END
