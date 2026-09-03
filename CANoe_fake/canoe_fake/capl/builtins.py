"""Catalog of CAPL built-in functions.

Each entry has: name, signature, return type, category, and a description.
Shared by autocomplete, tooltips, and the parser's "function does not exist" check.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaplFunction:
    name: str
    signature: str
    returns: str
    category: str
    doc: str

    @property
    def detail(self) -> str:
        return f"{self.returns} {self.signature}"


# (name, signature, returns, doc)  – category assigned per block below
_RAW: dict[str, list[tuple[str, str, str, str]]] = {
    # =====================================================================
    "Output / Write Window": [
        ("write", "write(char format[], ...)", "void",
         "Prints a line to the Write Window; format syntax is printf-style."),
        ("writeEx", "writeEx(long dest, long area, char format[], ...)", "void",
         "Prints to a specific Write Window tab with a given priority."),
        ("writeLineEx", "writeLineEx(long dest, long area, char format[], ...)", "void",
         "Like writeEx but automatically appends a newline."),
        ("writeDbgLevel", "writeDbgLevel(long level, char format[], ...)", "void",
         "Only prints when the current debug level >= level."),
        ("writeToLog", "writeToLog(char format[], ...)", "void",
         "Writes a line to the currently open logging file."),
        ("writeToLogEx", "writeToLogEx(char format[], ...)", "void",
         "Writes to the log even if the logging trigger hasn't fired yet."),
        ("writeClear", "writeClear(long tabIndex)", "void",
         "Clears the contents of a Write Window tab."),
        ("writeCreate", "writeCreate(char name[])", "long",
         "Creates a new Write Window tab, returns a handle."),
        ("writeDestroy", "writeDestroy(char name[])", "void",
         "Removes a tab created with writeCreate."),
        ("writeTextBkgColor", "writeTextBkgColor(long color)", "void",
         "Sets the background color for the next line of text."),
        ("writeTextColor", "writeTextColor(long color)", "void",
         "Sets the text color for the next line of text."),
        ("putValueToControl", "putValueToControl(char panel[], char control[], value)", "void",
         "Writes a value into a control on a panel."),
        ("runError", "runError(long errorCode, long value)", "void",
         "Reports a runtime error and (depending on configuration) stops the measurement."),
        ("beep", "beep(long frequency, long duration)", "void",
         "Sounds a beep through the system speaker."),
    ],
    # =====================================================================
    "String": [
        ("strlen", "strlen(char s[])", "long", "String length, not counting the terminator."),
        ("strncpy", "strncpy(char dest[], char src[], long n)", "void",
         "Copies up to n characters from src to dest."),
        ("strncat", "strncat(char dest[], char src[], long n)", "void",
         "Appends up to n characters of src to the end of dest."),
        ("strncmp", "strncmp(char s1[], char s2[], long n)", "long",
         "Compares the first n characters; returns 0 if equal."),
        ("strnicmp", "strnicmp(char s1[], char s2[], long n)", "long",
         "Like strncmp but case-insensitive."),
        ("strstr", "strstr(char haystack[], char needle[])", "long",
         "Position of the first occurrence of needle, -1 if not found."),
        ("strstr_off", "strstr_off(char haystack[], long offset, char needle[])", "long",
         "Like strstr but starts searching from position offset."),
        ("substr", "substr(char dest[], char src[], long start, long len)", "long",
         "Extracts len characters from src starting at start."),
        ("substr_cpy", "substr_cpy(char dest[], char src[], long start, long len, long destSize)", "long",
         "A safe version of substr, with destination-size checking."),
        ("strtol", "strtol(char s[], long base)", "long", "Converts a string to an integer using the given base."),
        ("strtoll", "strtoll(char s[], long base)", "int64", "Like strtol but returns a 64-bit value."),
        ("strtod", "strtod(char s[])", "double", "Converts a string to a floating-point number."),
        ("atol", "atol(char s[])", "long", "Converts a decimal string to a long."),
        ("atoi", "atoi(char s[])", "long", "Alias of atol."),
        ("atod", "atod(char s[])", "double", "Converts a string to a double."),
        ("ltoa", "ltoa(long value, char dest[], long base)", "void",
         "Converts an integer to a string using the given base."),
        ("snprintf", "snprintf(char dest[], long size, char format[], ...)", "long",
         "Formats a string into dest, capped at size bytes."),
        ("sprintf", "sprintf(char dest[], char format[], ...)", "long",
         "Formats a string into dest (unbounded — prefer snprintf)."),
        ("toUpper", "toUpper(char s[])", "void", "Uppercases the string in place."),
        ("toLower", "toLower(char s[])", "void", "Lowercases the string in place."),
        ("strReplace", "strReplace(char s[], long start, long len, char replacement[])", "long",
         "Replaces a substring with another string."),
        ("strSplit", "strSplit(char src[], char sep[], long index, char dest[], long destLen)", "long",
         "Splits a string by a separator and returns the element at index."),
    ],
    # =====================================================================
    "Math": [
        ("abs", "abs(long x)", "long", "Absolute value of an integer."),
        ("fabs", "fabs(double x)", "double", "Absolute value of a floating-point number."),
        ("sqrt", "sqrt(double x)", "double", "Square root."),
        ("pow", "pow(double base, double exp)", "double", "base raised to the power exp."),
        ("exp", "exp(double x)", "double", "Exponential function e^x."),
        ("log", "log(double x)", "double", "Natural logarithm."),
        ("log10", "log10(double x)", "double", "Base-10 logarithm."),
        ("sin", "sin(double rad)", "double", "Sine (radians)."),
        ("cos", "cos(double rad)", "double", "Cosine (radians)."),
        ("tan", "tan(double rad)", "double", "Tangent (radians)."),
        ("asin", "asin(double x)", "double", "Arcsine."),
        ("acos", "acos(double x)", "double", "Arccosine."),
        ("atan", "atan(double x)", "double", "Arctangent."),
        ("atan2", "atan2(double y, double x)", "double", "Arctangent of y/x, preserving the correct quadrant."),
        ("sinh", "sinh(double x)", "double", "Hyperbolic sine."),
        ("cosh", "cosh(double x)", "double", "Hyperbolic cosine."),
        ("tanh", "tanh(double x)", "double", "Hyperbolic tangent."),
        ("ceil", "ceil(double x)", "double", "Rounds up."),
        ("floor", "floor(double x)", "double", "Rounds down."),
        ("round", "round(double x)", "long", "Rounds to the nearest integer."),
        ("random", "random(long max)", "long", "Random number in the range [0, max)."),
        ("setRandomSeed", "setRandomSeed(long seed)", "void", "Seeds the random number generator."),
    ],
    # =====================================================================
    "Bit / Memory": [
        ("getBit", "getBit(value, long position)", "long", "Reads bit number position."),
        ("swapWord", "swapWord(word value)", "word", "Byte-swaps a 16-bit value."),
        ("swapInt", "swapInt(int value)", "int", "Byte-swaps a signed 16-bit value."),
        ("swapDword", "swapDword(dword value)", "dword", "Byte-swaps a 32-bit value."),
        ("swapLong", "swapLong(long value)", "long", "Byte-swaps a signed 32-bit value."),
        ("swapQword", "swapQword(qword value)", "qword", "Byte-swaps a 64-bit value."),
        ("elCount", "elCount(array[])", "long", "Number of elements in an array."),
        ("memcpy", "memcpy(dest[], src[])", "void", "Copies the contents of an array/struct."),
        ("memcpy_off", "memcpy_off(dest[], long destOff, src[], long srcOff, long n)", "long",
         "Copies n bytes with an offset on both sides."),
        ("memset", "memset(buffer[], byte value)", "void", "Sets an entire array to a single value."),
        ("memcmp", "memcmp(a[], b[], long n)", "long", "Compares n bytes of two memory regions."),
    ],
    # =====================================================================
    "Timer": [
        ("setTimer", "setTimer(timer t, long duration)", "long",
         "Arms a one-shot timer; msTimer is in ms, timer is in seconds."),
        ("setTimerCyclic", "setTimerCyclic(msTimer t, long firstDelay, long period)", "long",
         "Arms a timer that repeats on the given period."),
        ("cancelTimer", "cancelTimer(timer t)", "long", "Cancels a pending timer."),
        ("isTimerActive", "isTimerActive(timer t)", "long", "Returns 1 if the timer is currently running."),
        ("timeNow", "timeNow()", "int64",
         "Current measurement time, in 10 µs units."),
        ("timeNowNS", "timeNowNS()", "int64", "Current time, in nanoseconds."),
        ("timeDiff", "timeDiff(msg1, msg2)", "long",
         "Time difference between two bus objects."),
        ("getLocalTime", "getLocalTime(long time[])", "void",
         "Fills the system time into an array [year, month, day, hour, minute, second, ms]."),
        ("getLocalTimeString", "getLocalTimeString(char dest[])", "void",
         "System time as a string."),
        ("timeToString", "timeToString(int64 time, char dest[], long size)", "void",
         "Converts a timestamp to a human-readable string."),
    ],
    # =====================================================================
    "CAN / Bus": [
        ("output", "output(message msg)", "void", "Sends a frame onto the bus."),
        ("outputAfterTrigger", "outputAfterTrigger(message msg)", "void",
         "Sends a frame once the trigger condition is met."),
        ("canOnline", "canOnline()", "void", "Brings all CAN channels online."),
        ("canOffline", "canOffline()", "void", "Disconnects the CAN channel from the bus (no send/receive)."),
        ("canSetChannelOutput", "canSetChannelOutput(long channel, long mode)", "void",
         "Enables/disables transmission on a CAN channel."),
        ("canSetChannelMode", "canSetChannelMode(long channel, long txMode, long ackMode)", "void",
         "Configures the TX / ACK mode of a CAN channel."),
        ("resetCan", "resetCan()", "void", "Resets the CAN controller of the current node."),
        ("resetCanEx", "resetCanEx(long channel)", "void", "Resets the CAN controller of a specific channel."),
        ("setBtr", "setBtr(long channel, byte btr0, byte btr1)", "void",
         "Directly sets the bit-timing registers."),
        ("setCanCabsMode", "setCanCabsMode(long channel, long mode)", "void",
         "Sets the channel's CAB/piggyback mode."),
        ("getBusContextStr", "getBusContextStr(char dest[], long size)", "long",
         "Name of the current bus context (CAN1, LIN2, ...)."),
        ("chkStart", "chkStart(char checkName[])", "long", "Enables a configured check."),
        ("chkStop", "chkStop(char checkName[])", "long", "Disables a check."),
        ("chkQueryErrorCount", "chkQueryErrorCount(char checkName[])", "long",
         "Number of errors a check has detected."),
        ("CanTxErrorCount", "CanTxErrorCount(long channel)", "long", "The controller's transmit error counter."),
        ("CanRxErrorCount", "CanRxErrorCount(long channel)", "long", "The controller's receive error counter."),
        ("outputError", "outputError(long channel, long errorType)", "void",
         "Deliberately generates an error frame on the bus (for fault injection)."),
    ],
    # =====================================================================
    "Signal": [
        ("getSignal", "getSignal(signal s)", "double", "Reads a signal's physical value."),
        ("setSignal", "setSignal(signal s, double value)", "void", "Writes a signal's physical value."),
        ("getSignalTime", "getSignalTime(signal s)", "int64", "The time the signal was last updated."),
        ("isSignalUpdated", "isSignalUpdated(signal s)", "long",
         "Returns 1 if the signal has updated since the last read."),
        ("getSignalRaw", "getSignalRaw(signal s)", "int64", "Reads the raw (unconverted) value."),
        ("setSignalRaw", "setSignalRaw(signal s, int64 raw)", "void", "Writes the raw value of a signal."),
        ("getRxErrorCount", "getRxErrorCount()", "long", "Current receive error counter."),
        ("getTxErrorCount", "getTxErrorCount()", "long", "Current transmit error counter."),
        ("getValue", "getValue(envVar v)", "double", "Reads an environment variable's value."),
        ("putValue", "putValue(envVar v, value)", "void", "Writes an environment variable's value."),
    ],
    # =====================================================================
    "System Variable": [
        ("sysGetVariableInt", "sysGetVariableInt(sysvar v)", "long",
         "Reads an integer system variable."),
        ("sysGetVariableFloat", "sysGetVariableFloat(sysvar v)", "double",
         "Reads a floating-point system variable."),
        ("sysGetVariableString", "sysGetVariableString(sysvar v, char dest[], long size)", "long",
         "Reads a string system variable."),
        ("sysGetVariableData", "sysGetVariableData(sysvar v, byte dest[], long size)", "long",
         "Reads a byte-array system variable."),
        ("sysGetVariableIntArray", "sysGetVariableIntArray(sysvar v, long dest[], long size)", "long",
         "Reads an integer-array system variable."),
        ("sysSetVariableInt", "sysSetVariableInt(sysvar v, long value)", "long",
         "Writes an integer system variable."),
        ("sysSetVariableFloat", "sysSetVariableFloat(sysvar v, double value)", "long",
         "Writes a floating-point system variable."),
        ("sysSetVariableString", "sysSetVariableString(sysvar v, char value[])", "long",
         "Writes a string system variable."),
        ("sysSetVariableData", "sysSetVariableData(sysvar v, byte src[], long size)", "long",
         "Writes a byte-array system variable."),
        ("sysDefineVariable", "sysDefineVariable(char ns[], char name[], long initValue)", "long",
         "Creates a system variable dynamically at runtime."),
        ("sysUndefineVariable", "sysUndefineVariable(char ns[], char name[])", "long",
         "Removes a dynamically created system variable."),
        ("sysGetVariableQualifiedName", "sysGetVariableQualifiedName(sysvar v, char dest[], long size)", "long",
         "Gets the fully qualified namespace::name."),
    ],
    # =====================================================================
    "Diagnostics (UDS / OBD)": [
        ("diagSendRequest", "diagSendRequest(diagRequest req)", "long",
         "Sends a diagnostic request to the target ECU."),
        ("diagSendResponse", "diagSendResponse(diagResponse resp)", "long",
         "Sends a diagnostic response (used when simulating an ECU)."),
        ("diagSendNegativeResponse", "diagSendNegativeResponse(diagRequest req, byte nrc)", "long",
         "Sends a negative response with the given NRC."),
        ("diagGetParameter", "diagGetParameter(obj, char paramName[])", "double",
         "Reads a decoded parameter per the CDD/ODX description."),
        ("diagSetParameter", "diagSetParameter(obj, char paramName[], value)", "long",
         "Writes a decoded parameter."),
        ("diagGetParameterRaw", "diagGetParameterRaw(obj, char paramName[], byte dest[], long size)", "long",
         "Reads a parameter as raw bytes."),
        ("diagSetParameterRaw", "diagSetParameterRaw(obj, char paramName[], byte src[], long size)", "long",
         "Writes a parameter as raw bytes."),
        ("diagGetParameterString", "diagGetParameterString(obj, char paramName[], char dest[], long size)", "long",
         "Reads a string-typed parameter."),
        ("diagGetPrimitiveData", "diagGetPrimitiveData(obj, byte dest[], long size)", "long",
         "Gets all bytes of the primitive (including the SID)."),
        ("diagSetPrimitiveData", "diagSetPrimitiveData(obj, byte src[], long size)", "long",
         "Writes all bytes of the primitive."),
        ("diagGetPrimitiveSize", "diagGetPrimitiveSize(obj)", "long", "The primitive's size in bytes."),
        ("diagResize", "diagResize(obj, long newSize)", "long", "Resizes the primitive."),
        ("diagGetResponseCode", "diagGetResponseCode(diagResponse resp)", "long",
         "The response's NRC, 0 if this is a positive response."),
        ("diagIsPositiveResponse", "diagIsPositiveResponse(diagResponse resp)", "long",
         "Returns 1 if this is a positive response."),
        ("diagIsNegativeResponse", "diagIsNegativeResponse(diagResponse resp)", "long",
         "Returns 1 if this is a negative response."),
        ("diagGetLastResponseCode", "diagGetLastResponseCode()", "long",
         "NRC of the most recent response on the diagnostic channel."),
        ("diagSetTarget", "diagSetTarget(char ecuQualifier[])", "long",
         "Selects the target ECU for subsequent diagnostic commands."),
        ("diagStartTesterPresent", "diagStartTesterPresent(char ecu[])", "long",
         "Starts sending periodic TesterPresent (0x3E)."),
        ("diagStopTesterPresent", "diagStopTesterPresent(char ecu[])", "long",
         "Stops sending TesterPresent."),
        ("diagSetVirtualEcuSupport", "diagSetVirtualEcuSupport(long enable)", "long",
         "Enables/disables virtual ECU support."),
        ("diagGetHeaderSize", "diagGetHeaderSize(obj)", "long", "Size of the primitive's header portion."),
        ("diagGetEcuQualifier", "diagGetEcuQualifier(obj, char dest[], long size)", "long",
         "The ECU qualifier name attached to the primitive."),
        ("diagSetIoDataSize", "diagSetIoDataSize(obj, long size)", "long",
         "Sets the size of the I/O data region."),
        ("CanTpSetTxPadding", "CanTpSetTxPadding(long enable, byte padByte)", "long",
         "Enables padding for ISO-TP frames on transmit."),
        ("CanTpSetBlockSize", "CanTpSetBlockSize(long blockSize)", "long",
         "Sets the ISO-TP Block Size (flow control)."),
        ("CanTpSetSTmin", "CanTpSetSTmin(long stMin)", "long",
         "Sets the minimum Separation Time between consecutive frames."),
    ],
    # =====================================================================
    "Test Feature Set": [
        ("TestModuleTitle", "TestModuleTitle(char title[])", "void", "Sets the test module's title in the report."),
        ("TestModuleDescription", "TestModuleDescription(char desc[])", "void", "Describes the test module."),
        ("TestCaseTitle", "TestCaseTitle(char id[], char title[])", "void", "Sets the title of a test case."),
        ("TestCaseDescription", "TestCaseDescription(char desc[])", "void", "Describes a test case."),
        ("TestStep", "TestStep(char id[], char format[], ...)", "void", "Logs a test step (informational)."),
        ("TestStepPass", "TestStepPass(char id[], char format[], ...)", "void", "Logs a test step with a PASS verdict."),
        ("TestStepFail", "TestStepFail(char id[], char format[], ...)", "void", "Logs a test step with a FAIL verdict."),
        ("TestStepWarning", "TestStepWarning(char id[], char format[], ...)", "void", "Logs a test step at warning level."),
        ("TestStepFailAndAbort", "TestStepFailAndAbort(char id[], char format[], ...)", "void",
         "Marks FAIL and aborts the current test case."),
        ("TestReportWriteHeading", "TestReportWriteHeading(long level, char text[])", "void",
         "Inserts a heading into the test report."),
        ("TestReportAddMiscInfo", "TestReportAddMiscInfo(char label[], char value[])", "void",
         "Adds a line of miscellaneous info to the report."),
        ("TestReportAddMiscInfoBlock", "TestReportAddMiscInfoBlock(char title[])", "void",
         "Opens a block of miscellaneous info in the report."),
        ("TestReportAddWindowCapture", "TestReportAddWindowCapture(char window[], char caption[])", "void",
         "Captures a window screenshot and attaches it to the report."),
        ("TestWaitForTimeout", "TestWaitForTimeout(long ms)", "long", "Waits for a fixed duration."),
        ("TestWaitForMessage", "TestWaitForMessage(message msg, long timeout)", "long",
         "Waits to receive a specific CAN message."),
        ("TestWaitForSignalMatch", "TestWaitForSignalMatch(signal s, double value, long timeout)", "long",
         "Waits for a signal to reach an exact value."),
        ("TestWaitForSignalInRange", "TestWaitForSignalInRange(signal s, double min, double max, long timeout)", "long",
         "Waits for a signal to fall within a value range."),
        ("TestWaitForSysVar", "TestWaitForSysVar(sysvar v, long timeout)", "long",
         "Waits for a system variable to change."),
        ("TestWaitForSysVarMatch", "TestWaitForSysVarMatch(sysvar v, double value, long timeout)", "long",
         "Waits for a system variable to reach a value."),
        ("TestWaitForTextEvent", "TestWaitForTextEvent(char text[], long timeout)", "long",
         "Waits for a text event raised by another node."),
        ("TestSupplyTextEvent", "TestSupplyTextEvent(char text[])", "void", "Raises a text event."),
        ("TestJoinTextEvent", "TestJoinTextEvent(char text[])", "long", "Adds a text event to the wait set."),
        ("TestJoinMessageEvent", "TestJoinMessageEvent(message msg)", "long", "Adds a message to the wait set."),
        ("TestJoinSysVarEvent", "TestJoinSysVarEvent(sysvar v)", "long", "Adds a sysvar to the wait set."),
        ("TestWaitForAnyJoinedEvent", "TestWaitForAnyJoinedEvent(long timeout)", "long",
         "Waits for any event in the wait set."),
        ("TestWaitForAllJoinedEvents", "TestWaitForAllJoinedEvents(long timeout)", "long",
         "Waits for all events in the wait set."),
        ("TestGetWaitEventMessageData", "TestGetWaitEventMessageData(message dest)", "long",
         "Gets the message data of the event that just woke the wait."),
        ("TestModuleAbort", "TestModuleAbort()", "void", "Aborts the entire test module."),
        ("TestGetVerdictLastTestCase", "TestGetVerdictLastTestCase()", "long",
         "The verdict of the test case that just finished."),
        ("TestGetVerdictModule", "TestGetVerdictModule()", "long", "The test module's overall verdict."),
        ("TestSetVerdictModule", "TestSetVerdictModule(long verdict)", "void", "Sets the test module's verdict."),
        ("TestAddCondition", "TestAddCondition(long conditionHandle)", "long", "Adds a monitoring condition."),
        ("TestCheckAddSignalRangeViolation", "TestCheckAddSignalRangeViolation(signal s, double min, double max)", "long",
         "Registers a check: a signal exceeding the allowed range gets recorded."),
    ],
    # =====================================================================
    "File I/O": [
        ("openFileRead", "openFileRead(char path[], long binary)", "dword",
         "Opens a file for reading; returns a handle, 0 on error."),
        ("openFileWrite", "openFileWrite(char path[], long binary)", "dword", "Opens a file for writing (overwrites)."),
        ("openFileAppend", "openFileAppend(char path[], long binary)", "dword", "Opens a file for appending."),
        ("fileClose", "fileClose(dword handle)", "long", "Closes a file."),
        ("fileGetString", "fileGetString(char dest[], long size, dword handle)", "long",
         "Reads one line of text from a file."),
        ("fileGetStringSZ", "fileGetStringSZ(char dest[], long size, dword handle)", "long",
         "Reads a NUL-terminated string."),
        ("filePutString", "filePutString(char s[], long len, dword handle)", "long", "Writes a string to a file."),
        ("fileGetBinaryBlock", "fileGetBinaryBlock(byte dest[], long size, dword handle)", "long",
         "Reads a binary block."),
        ("filePutBinaryBlock", "filePutBinaryBlock(byte src[], long size, dword handle)", "long",
         "Writes a binary block."),
        ("fileRewind", "fileRewind(dword handle)", "long", "Rewinds the read/write cursor to the start of the file."),
        ("fileReadInt", "fileReadInt(char section[], char key[], long defaultValue, char iniPath[])", "long",
         "Reads an integer from an INI file."),
        ("fileReadString", "fileReadString(char section[], char key[], char def[], char dest[], long size, char iniPath[])", "long",
         "Reads a string from an INI file."),
        ("fileWriteString", "fileWriteString(char section[], char key[], char value[], char iniPath[])", "long",
         "Writes a string to an INI file."),
        ("fileExists", "fileExists(char path[])", "long", "Checks whether a file exists."),
        ("fileDelete", "fileDelete(char path[])", "long", "Deletes a file."),
        ("mkDir", "mkDir(char path[])", "long", "Creates a directory."),
    ],
    # =====================================================================
    "Panel / UI": [
        ("openPanel", "openPanel(char panelName[])", "void", "Opens a panel."),
        ("closePanel", "closePanel(char panelName[])", "void", "Closes a panel."),
        ("enablePanel", "enablePanel(char panelName[], long enable)", "void", "Enables/disables interaction with a panel."),
        ("enableControl", "enableControl(char panel[], char control[], long enable)", "void",
         "Enables/disables a control on a panel."),
        ("setControlVisibility", "setControlVisibility(char panel[], char control[], long visible)", "void",
         "Shows/hides a control."),
        ("setControlBackColor", "setControlBackColor(char panel[], char control[], long color)", "void",
         "Sets a control's background color."),
        ("setControlForeColor", "setControlForeColor(char panel[], char control[], long color)", "void",
         "Sets a control's text color."),
        ("setControlProperty", "setControlProperty(char panel[], char control[], char prop[], value)", "void",
         "Sets any property of a control."),
        ("getControlProperty", "getControlProperty(char panel[], char control[], char prop[])", "double",
         "Reads a control's property."),
        ("setWriteDbgLevel", "setWriteDbgLevel(long level)", "void", "Sets the debug level used by writeDbgLevel."),
    ],
    # =====================================================================
    "Logging / Replay": [
        ("startLogging", "startLogging(long blockIndex)", "void", "Starts recording the given logging block."),
        ("stopLogging", "stopLogging(long blockIndex)", "void", "Stops recording."),
        ("triggerLogging", "triggerLogging(long blockIndex)", "void", "Fires the logging block's trigger."),
        ("setLogFileName", "setLogFileName(long blockIndex, char path[])", "void", "Sets the log file name."),
        ("replayStart", "replayStart(char blockName[])", "long", "Starts a replay block."),
        ("replayStop", "replayStop(char blockName[])", "long", "Stops the replay."),
        ("replaySuspend", "replaySuspend(char blockName[])", "long", "Suspends the replay."),
        ("replayResume", "replayResume(char blockName[])", "long", "Resumes the replay."),
        ("replayState", "replayState(char blockName[])", "long", "Current state of a replay block."),
    ],
    # =====================================================================
    "Measurement / Environment": [
        ("stop", "stop()", "void", "Stops the measurement."),
        ("stopMeasurement", "stopMeasurement()", "void", "Alias of stop()."),
        ("getMeasurementRunName", "getMeasurementRunName(char dest[], long size)", "long",
         "The current measurement run's name."),
        ("getProfilePath", "getProfilePath(char dest[], long size)", "long", "Path to the configuration directory."),
        ("getConfigurationPath", "getConfigurationPath(char dest[], long size)", "long",
         "Path to the open .cfg configuration file."),
        ("getNodeName", "getNodeName(char dest[], long size)", "long", "The current CAPL node's name."),
        ("getSystemVarsPath", "getSystemVarsPath(char dest[], long size)", "long",
         "Path to the system-variable definition file."),
        ("sysExec", "sysExec(char command[], char args[])", "long", "Runs an external program."),
        ("sysExecCmd", "sysExecCmd(char command[], char args[])", "long", "Runs a command through the command shell."),
        ("sysMinorVersion", "sysMinorVersion()", "long", "CANoe's minor version number."),
        ("sysMajorVersion", "sysMajorVersion()", "long", "CANoe's major version number."),
        ("callAllOnEnvVar", "callAllOnEnvVar()", "void",
         "Calls every on envVar handler once (used to initialize state)."),
    ],
    # =====================================================================
    "LIN": [
        ("linSendHeader", "linSendHeader(long id)", "long", "Master sends a LIN header."),
        ("linStartScheduler", "linStartScheduler()", "long", "Starts the LIN scheduler."),
        ("linStopScheduler", "linStopScheduler()", "long", "Stops the LIN scheduler."),
        ("linChangeSchedTable", "linChangeSchedTable(long tableIndex)", "long", "Switches to a different schedule table."),
        ("linGetSlaveResponse", "linGetSlaveResponse(long id, byte dest[])", "long",
         "Reads a slave's response data."),
        ("linSetSlaveResponse", "linSetSlaveResponse(long id, byte src[], long dlc)", "long",
         "Sets the response data for a simulated slave."),
        ("linSendWakeup", "linSendWakeup()", "long", "Sends a wakeup signal on the LIN bus."),
        ("linSetGotoSleep", "linSetGotoSleep()", "long", "Puts the LIN bus into sleep mode."),
    ],
    # =====================================================================
    "FlexRay": [
        ("frSetSlotUsage", "frSetSlotUsage(long slotId, long cycle, long usage)", "long",
         "Enables/disables use of a FlexRay slot."),
        ("frStartCommunication", "frStartCommunication(long channel)", "long", "Starts FlexRay communication."),
        ("frHaltCommunication", "frHaltCommunication(long channel)", "long", "Stops FlexRay communication."),
        ("frGetPOCState", "frGetPOCState(long channel)", "long", "The Protocol Operation Control state."),
        ("frTriggerWakeup", "frTriggerWakeup(long channel)", "long", "Sends a FlexRay wakeup signal."),
        ("frUpdatePDU", "frUpdatePDU(frPDU pdu)", "long", "Updates the contents of a FlexRay PDU."),
    ],
    # =====================================================================
    "Ethernet": [
        ("ethOutputPacket", "ethOutputPacket(ethernetPacket pkt)", "long", "Sends an Ethernet packet."),
        ("ethGetMacAddress", "ethGetMacAddress(long channel, byte dest[])", "long",
         "Reads a channel's MAC address."),
        ("ethGetLinkStatus", "ethGetLinkStatus(long channel)", "long", "Link status (up/down)."),
        ("ethSetLinkStatus", "ethSetLinkStatus(long channel, long status)", "long",
         "Forces a link status (used for fault injection)."),
        ("ethGetPhyState", "ethGetPhyState(long channel)", "long", "Current PHY state."),
        ("ipGetAddressAsString", "ipGetAddressAsString(long addr, char dest[], long size)", "long",
         "Converts a numeric IP address to a string."),
        ("ipGetAddressAsNumber", "ipGetAddressAsNumber(char addr[])", "dword",
         "Converts a string IP address to a number."),
        ("udpOpen", "udpOpen(dword localAddr, dword localPort)", "dword", "Opens a UDP socket."),
        ("udpSendTo", "udpSendTo(dword socket, dword addr, dword port, byte data[], dword size)", "long",
         "Sends data over UDP."),
        ("tcpOpen", "tcpOpen(dword localAddr, dword localPort)", "dword", "Opens a TCP socket."),
        ("tcpConnect", "tcpConnect(dword socket, dword addr, dword port, dword flags)", "long",
         "Connects a TCP socket to a server."),
        ("socketClose", "socketClose(dword socket)", "long", "Closes a socket."),
    ],
    # =====================================================================
    "J1939": [
        ("j1939SendPg", "j1939SendPg(pg)", "long", "Sends a J1939 Parameter Group."),
        ("j1939GetPgn", "j1939GetPgn(pg)", "dword", "Gets a Parameter Group's PGN."),
        ("j1939SetAddress", "j1939SetAddress(char node[], byte address)", "long",
         "Sets the source address for a J1939 node."),
        ("j1939RequestPg", "j1939RequestPg(dword pgn, byte destAddr)", "long",
         "Sends a request for a given PGN."),
    ],
}


# ---------------------------------------------------------------------------
# Build the lookup table
# ---------------------------------------------------------------------------

FUNCTIONS: dict[str, CaplFunction] = {}
for _category, _items in _RAW.items():
    for _name, _sig, _ret, _doc in _items:
        FUNCTIONS[_name] = CaplFunction(_name, _sig, _ret, _category, _doc)

CATEGORIES: tuple[str, ...] = tuple(_RAW.keys())

#: case-insensitive lookup — CAPL allows calling TestStepPass / teststeppass
_LOWER_INDEX: dict[str, str] = {n.lower(): n for n in FUNCTIONS}


def lookup(name: str) -> CaplFunction | None:
    fn = FUNCTIONS.get(name)
    if fn is not None:
        return fn
    canonical = _LOWER_INDEX.get(name.lower())
    return FUNCTIONS[canonical] if canonical else None


def is_builtin(name: str) -> bool:
    return lookup(name) is not None


def names_by_category(category: str) -> list[str]:
    return sorted(n for n, f in FUNCTIONS.items() if f.category == category)


def all_names() -> list[str]:
    return sorted(FUNCTIONS)
