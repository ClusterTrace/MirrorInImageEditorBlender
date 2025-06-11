# MirrorInImageEditorBlender
An addon for blender that allows mirroring of the image in the image editor

Can install by from Blender's addon menu by pressing install and then selecting the python file as the addon. Then check the box for the addon that is added.
You can find the panel inside the Image Editor window, where it is called "Mirroring".

Parts of the readme and other descriptions are slightly out of date. The instructions.txt should give info the newer stuff like the mirroring in 3D using baking and the symmetry line.

## How to use:
1. Have an image editor window open in blender with a texture selected
2. Snapshot the image in the image editor using the "Snapshot" button (make sure an object is selected in the mirror settings if you want to mirror in 3D)
3. Draw on the texture in whatever method you prefer (examples include using the texture editing mode on a model or the paint mode in the image editor)
4. Press the mirror button of your choice for your preferred outcome
  - press "Mirror Changes 2D" if you are mirroring in 2D (don't forget to play around with the 2D positions and angle that determines the line it mirrors over (defaults to a horizontal line))
  - press "Mirror Changes 2D As Mask" if you want what you drew to be a mask for what should be mirrored in 2D
  - Press "Mirror Changes" if you are mirroring in 3D (don't forget to play around with the world axis to mirror over)
  - Press "Mirror Changes As Mask"if you want what you drew to be a mask for what should be mirrored in 3D
5. If you are happy with the changes made once the mirroring finished, snapshot again to ensure they aren't reverted in future mirrorings. Else, you can hit "Revert to Snapshot" to undo what was changed.

## Current Features:
- Can snapshot the original image using the "Snapshot" button, which will be used to determine what is mirrored in the other features.
  - Can revert to this snapshot using the "Revert To Snapshot" button
- Can mirror in 2D by using a point in the UV space (default is in the middle) and an angle to determine a line to flip the changes made over
  - Can try to visualize the line using the "Invert Pixels On Symmetry Line" feature. Just make sure to invert them again before making any real changes.
  - Can mirror existing parts by using "Mirror Changes 2D As Mask" which will use what you drew over to determine what of the original snapshot to mirror.
- Can mirror in 3D by giving it an object and UV map (defaults to UVMap), which will then use the geometry nodes added from snapshotting to get mirror cordinates and then mirror pixels.
  - Can mirror existing parts by using "Mirror Changes As Mask" which will use what you drew over to determine what of the original snapshot to mirror.
  - Can create a snapshot mapping using "Create Mirror Map", which will create a mapping to speed up future mirrorings over the currently selected axis in 3D. Only one mapping can exist at a time.
  - Can change what world axis is used in the mirroring using the x, y, and z buttons in the 3D mirroring part of the panel
  - Can remove the snapshot modifiers, as in the geometry nodes added by snapshoting, by pressing the "Remove Snapshot Modifiers" button. This will require snapshotting again to be able to use 3D mirroring.
- Can try to fill in small pixel gaps (artifacts that exist when mirroring in 2D on increments that are not multiples of 45 degrees and sometimes on 3D mirroring for specific models) when mirroring by checking "Pixel Gap Fill"
  - Can change the threshold for how many nearby pixels must have been altered to update the current one by changing "Pixel Gap Fill Threshold" (defaults to 6)
  - Can change whether the pixel's self value, as in its color, is factored into the new color it is given by enabling "Pixel Gap Fill Self Blend"


## Known Issues:
- Pixel gaps (one pixel wide holes where values weren't mirrored) appear when mirroring in 3D on some models and sometimes when mirroring in 2D if using an angle that isn't a multiple of 45 degrees
- Mirroring, especially in 3D, is a slow process. This is mostly caused by the lack of parallelism and gpu accelleration, especially in the geometry nodes. This means blender will appear to freeze when given the command to mirror, but it is likely just still processing. 2D mirroring a 4k texture should take only a couple of minutes for a modern cpu, but can take days to mirror a 4k texture for a 20,000 polygon model.
- Overlapping UVs can likely cause errors or unintended effects
- Addon isn't airtight on user input, meaning the user can make changes the addon doesn't account for. Examples include editing the object a mapping was made on after it was mapped, resulting in the mapping being outdated but still used.

## Possible future features:
- gpu accelerated or parallized processing (couldn't figure it out in my initial researching for the addon)
- loading bar instead of freezing blender using a modal
- mirroring changed as a difference (this means mirroring the changes made to pixels rather than copying the pixels values)
