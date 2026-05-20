NAME_INPUT = 'input[aria-label*="name" i]'
MIC_TOGGLE = '[aria-label*="microphone" i][role="button"]'
CAM_TOGGLE = '[aria-label*="camera" i][role="button"]'
ASK_TO_JOIN_BTN = 'button:has-text("Ask to join")'
JOIN_NOW_BTN = 'button:has-text("Join now")'
CONSENT_JOIN_NOW_BTN = 'button:has-text("Join now")'
GOT_IT_BTN = 'button:has-text("Got it")'
JOIN_HERE_TOO_BTN = 'button:has-text("Join here too")'
SWITCH_HERE_BTN = 'button:has-text("Switch here")'
LEAVE_BTN = '[aria-label*="leave call" i]'
DENIED_TEXT = 'text="No one responded to your request"'
RISK_QUEUE_TEXT = "text=/suspicious|automated|could not be verified/i"
REMOVED_DIALOG = 'text="You\'ve been removed"'
MEETING_ENDED = 'text="You left the meeting"'
PARTICIPANT_LIST_BTNS = (
    'button[aria-label*="Show everyone" i]',
    'button[aria-label*="People" i]',
    'button[aria-label*="participant" i]',
    'button[aria-label*="mọi người" i]',
    'button[aria-label*="người tham gia" i]',
)
PARTICIPANT_NAMES = "[data-participant-id]"
