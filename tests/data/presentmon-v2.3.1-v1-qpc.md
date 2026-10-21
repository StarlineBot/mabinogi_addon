# PresentMon 2.3.1 console contract fixture

Header from WriteCsvHeader<FrameMetrics1> in the pinned upstream source:
https://github.com/GameTechDev/PresentMon/blob/v2.3.1/PresentMon/CsvOutput.cpp

Arguments: --v1_metrics --qpc_time --no_track_display --no_track_gpu --no_track_input.
Rows are synthetic 50 FPS events with QPC frequency 1000, not a Windows/game capture.
Relative TimeInSeconds deliberately differs from the absolute QPCTime column.
QPCTime is the raw PresentStartTime integer for --qpc_time; msBetweenPresents is milliseconds.
Do not substitute the modern FrameMetrics header or relative seconds for this contract.
