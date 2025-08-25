# MirrorInImageEditorBlender
An addon for blender that allows mirroring of the image in the image editor

Can install by from Blender's addon menu by pressing install and then selecting the python file (MirrorAddon.py) as the addon. Then check the box for the addon that is added (newer versions of blender default to activating after installing).
You can find the panel inside the Image Editor window, where it is called "Mirroring".

## How to use:
- Install the MirrorAddon.py file (can download all of the code from the code button or select the MirrorAddon.py file and use the ... button to select download)
- Instructions for use are included in Instructions.txt

## Current Features:
- Can snapshot the original image using the "Snapshot" button, which will be used to determine what is mirrored in the other features.
  - Can revert to this snapshot using the "Revert To Snapshot" button
- Can mirror in 2D by using a point in the UV space (default is in the middle) and an angle to determine a line to flip the changes made over
  - A symmetry line can be made visible to assist visually
  - Can mirror existing parts by using "Mirror Changes 2D As Mask" which will use what you drew over to determine what of the original snapshot to mirror.
- Can mirror in 3D by giving it an object and UV map (defaults to UVMap), which will then get mirror cordinates and then mirror pixels.
  - Can mirror existing parts by using "Mirror Changes As Mask" which will use what you drew over to determine what of the original snapshot to mirror.
  - Can create a snapshot mapping using "Create Mirror Map", which will create a mapping to speed up future mirrorings over the currently selected axis in 3D. Only one mapping can exist at a time. Creating a mapping is very expensive, as the process is not parallel and not gpu accelerated, so use with caution.
  - Can change what world axis is used in the mirroring using the x, y, and z buttons in the 3D mirroring part of the panel
  - The prefered mirror method utilizes the baking system in Blender (within Cycles) to mirror pixels by mirroring an object and baking part of a mirror to the current texture. This is less prone to pixel gap artifacts and can be gpu accelerated by utilizing the gpu for Cycles.
- Can try to fill in small pixel gaps (artifacts that exist when mirroring in 2D on increments that are not multiples of 45 degrees and sometimes on 3D mirroring for specific models) when mirroring by checking "Pixel Gap Fill"
  - Can change the threshold for how many nearby pixels must have been altered to update the current one by changing "Pixel Gap Fill Threshold" (defaults to 6)
  - Can change whether the pixel's self value, as in its color, is factored into the new color it is given by enabling "Pixel Gap Fill Self Blend"


## Known Issues:
- Pixel gaps (one pixel wide holes where values weren't mirrored) appear when mirroring in 3D on some models and sometimes when mirroring in 2D if using an angle that isn't a multiple of 45 degrees
- Mirroring, especially in 3D, is a slow process. This is mostly caused by the lack of parallelism and gpu accelleration, especially in the geometry nodes or python api. This means blender will appear to freeze when given the command to mirror, but it is likely just still processing. 2D mirroring a 4k texture should take only a couple of minutes for a modern cpu, but can take days to 3D mirror a 4k texture for a 20,000 polygon model. Should utilize the baking mirror method to help overcome the time issue for 3D mirroring.
- Overlapping UVs can likely cause errors or unintended effects
- Addon isn't airtight on user input, meaning the user can make changes the addon doesn't account for. Examples include editing the object a mapping was made on after it was mapped, resulting in the mapping being outdated but still used.

## Bugs:
- mirroring using the non-baking mirror methods in 3D seems unable to mirror to the very edge of the texture (meaning last column of pixels isn't mirrored to)
- line thickness variable does not seem to work for the symmetry line
- 2D mirroring can mirror into adjacent tiles, resulting in mirrors back onto the existing tile (possible UV tiling issue with Blender, but likely preventable by catching values outside of 0-1 range)

## Possible future features:
- gpu accelerated or parallized processing using the gpu library for 2D mirroring
- loading bar instead of freezing blender using a modal
