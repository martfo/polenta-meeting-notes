#import "ObjCSupport.h"

NSError *_Nullable ObjCTryCatch(void (NS_NOESCAPE ^block)(void)) {
    @try {
        block();
        return nil;
    } @catch (NSException *exception) {
        NSString *message = exception.reason ?: exception.name ?: @"Objective-C exception";
        return [NSError errorWithDomain:@"ObjCException"
                                   code:0
                               userInfo:@{NSLocalizedDescriptionKey: message}];
    }
}
